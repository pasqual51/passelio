"""Optional RFC 6238 TOTP with atomic replay protection and one-use recovery codes."""
import base64
import hashlib
import hmac
import json
import io
import os
import secrets
import struct
import time
from pathlib import Path
from urllib.parse import quote, urlencode

from flask import g, jsonify, request
from werkzeug.security import check_password_hash
import qrcode


def totp(secret, step, digits=6):
    key=base64.b32decode(secret,casefold=True)
    digest=hmac.new(key,struct.pack('>Q',step),hashlib.sha1).digest()
    offset=digest[-1]&15
    return str((struct.unpack('>I',digest[offset:offset+4])[0]&0x7fffffff)%10**digits).zfill(digits)


def init_mfa(app,db,root,protected,fail,audit,rate_limit):
    folder=Path(root)/'mfa-secrets';folder.mkdir(mode=0o700,exist_ok=True)
    with db() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS mfa_factors(
          user_id INTEGER PRIMARY KEY REFERENCES users(id),secret_id TEXT,enabled INTEGER NOT NULL DEFAULT 0,
          pending_id TEXT,pending_expires INTEGER NOT NULL DEFAULT 0,last_step INTEGER NOT NULL DEFAULT -1,
          recovery_hashes TEXT NOT NULL DEFAULT '[]');''')

    def read_secret(sid):
        if not isinstance(sid,str) or len(sid)!=48 or any(c not in '0123456789abcdef' for c in sid):return None
        path=folder/sid
        if not path.is_file() or path.is_symlink():return None
        return path.read_text(encoding='ascii')

    def matching_step(secret,code,last=-1):
        if not secret or not isinstance(code,str) or len(code)!=6 or not code.isascii() or not code.isdigit():return None
        now=int(time.time())//30
        for step in (now,now-1,now+1):
            if step>last and step>=0 and hmac.compare_digest(totp(secret,step),code):return step
        return None

    def check(c,uid,code):
        factor=c.execute('SELECT * FROM mfa_factors WHERE user_id=? AND enabled=1',(uid,)).fetchone()
        if not factor:return True
        if not isinstance(code,str) or len(code)>128:return False
        step=matching_step(read_secret(factor['secret_id']),code,factor['last_step'])
        if step is not None:
            c.execute('UPDATE mfa_factors SET last_step=? WHERE user_id=?',(step,uid))
            return True
        normalized=code.strip().lower().replace('-','')
        if len(normalized)!=24 or any(ch not in '0123456789abcdef' for ch in normalized):return False
        hashed=hashlib.sha256(normalized.encode()).hexdigest()
        hashes=json.loads(factor['recovery_hashes'])
        found=next((i for i,v in enumerate(hashes) if hmac.compare_digest(v,hashed)),None)
        if found is None:return False
        hashes.pop(found)
        c.execute('UPDATE mfa_factors SET recovery_hashes=? WHERE user_id=?',(json.dumps(hashes),uid))
        audit(c,'mfa.recovery_used',str(uid))
        return True

    def verify_login(uid,code,connection):
        enabled=connection.execute('SELECT 1 FROM mfa_factors WHERE user_id=? AND enabled=1',(uid,)).fetchone()
        if not enabled:return None
        if not code:return 'mfa_required'
        if not check(connection,uid,code):return 'mfa_invalid'
        return None
    app.verify_mfa_login=verify_login

    def reauthenticate(body):
        if not rate_limit('mfa-settings:'+str(g.user['id']),10):return fail('rate_limited',429)
        password=body.get('password')
        if not isinstance(password,str) or len(password)>1024 or not check_password_hash(g.user['password'],password):return fail('invalid_credentials',401)
        return None

    @app.get('/api/me/mfa')
    @protected()
    def state():
        with db() as c:row=c.execute('SELECT enabled,recovery_hashes FROM mfa_factors WHERE user_id=?',(g.user['id'],)).fetchone()
        return jsonify(enabled=bool(row and row['enabled']),recovery_remaining=len(json.loads(row['recovery_hashes'])) if row and row['enabled'] else 0)

    @app.post('/api/me/mfa/setup')
    @protected()
    def setup():
        body=request.get_json(silent=True) or {}
        error=reauthenticate(body)
        if error:return error
        sid=secrets.token_hex(24);secret=base64.b32encode(secrets.token_bytes(20)).decode('ascii')
        old=None
        with db(True) as c:
            current=c.execute('SELECT * FROM mfa_factors WHERE user_id=?',(g.user['id'],)).fetchone()
            if current and current['enabled']:return fail('mfa_already_enabled',409)
            old=current['pending_id'] if current else None
            path=folder/sid
            try:
                with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w',encoding='ascii') as f:
                    f.write(secret);f.flush();os.fsync(f.fileno())
                c.execute('INSERT INTO mfa_factors(user_id,pending_id,pending_expires) VALUES(?,?,?) '
                          'ON CONFLICT(user_id) DO UPDATE SET pending_id=excluded.pending_id,pending_expires=excluded.pending_expires',
                          (g.user['id'],sid,int(time.time())+600))
                audit(c,'mfa.setup_started',str(g.user['id']))
            except Exception:
                path.unlink(missing_ok=True)
                raise
        if old:(folder/old).unlink(missing_ok=True)
        issuer=app.system_settings()['application_name']
        uri='otpauth://totp/'+quote(issuer+':'+g.user['email'],safe='')+'?'+urlencode(dict(secret=secret,issuer=issuer,algorithm='SHA1',digits=6,period=30))
        # Generate locally. Never disclose provisioning secrets to a QR service.
        qr=qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,box_size=6,border=4)
        qr.add_data(uri);qr.make(fit=True)
        image=io.BytesIO();qr.make_image(fill_color='black',back_color='white').save(image,format='PNG')
        return jsonify(secret=secret,uri=uri,expires_in=600,
                       qr_png='data:image/png;base64,'+base64.b64encode(image.getvalue()).decode('ascii'))

    @app.post('/api/me/mfa/enable')
    @protected()
    def enable():
        body=request.get_json(silent=True) or {}
        if not rate_limit('mfa-enable:'+str(g.user['id']),10):return fail('rate_limited',429)
        with db(True) as c:
            current=c.execute('SELECT * FROM mfa_factors WHERE user_id=?',(g.user['id'],)).fetchone()
            if not current or current['enabled'] or current['pending_expires']<=time.time():return fail('mfa_setup_expired',410)
            step=matching_step(read_secret(current['pending_id']),body.get('code'))
            if step is None:return fail('mfa_invalid',401)
            codes=[secrets.token_hex(12) for _ in range(10)]
            hashes=[hashlib.sha256(code.encode()).hexdigest() for code in codes]
            c.execute('UPDATE mfa_factors SET enabled=1,secret_id=pending_id,pending_id=NULL,pending_expires=0,last_step=?,recovery_hashes=? WHERE user_id=?',
                      (step,json.dumps(hashes),g.user['id']))
            c.execute('DELETE FROM sessions WHERE user_id=?',(g.user['id'],))
            audit(c,'mfa.enabled',str(g.user['id']))
        response=jsonify(ok=True,recovery_codes=['-'.join(code[i:i+8] for i in range(0,24,8)) for code in codes])
        response.delete_cookie('passelio_session')
        return response

    @app.post('/api/me/mfa/disable')
    @protected()
    def disable():
        body=request.get_json(silent=True) or {}
        error=reauthenticate(body)
        if error:return error
        with db(True) as c:
            row=c.execute('SELECT * FROM mfa_factors WHERE user_id=? AND enabled=1',(g.user['id'],)).fetchone()
            if not row:return fail('invalid_input')
            if not check(c,g.user['id'],body.get('code')):return fail('mfa_invalid',401)
            c.execute('DELETE FROM mfa_factors WHERE user_id=?',(g.user['id'],))
            c.execute('DELETE FROM sessions WHERE user_id=?',(g.user['id'],))
            audit(c,'mfa.disabled',str(g.user['id']))
        for sid in (row['secret_id'],row['pending_id']):
            if sid:(folder/sid).unlink(missing_ok=True)
        response=jsonify(ok=True);response.delete_cookie('passelio_session');return response

    previous=app.cleanup
    def cleanup():
        count=previous()
        with db(True) as c:
            rows=c.execute('SELECT pending_id FROM mfa_factors WHERE pending_id IS NOT NULL AND pending_expires<=?',(time.time(),)).fetchall()
            c.execute('UPDATE mfa_factors SET pending_id=NULL,pending_expires=0 WHERE pending_expires<=?',(time.time(),))
            for row in rows:(folder/row['pending_id']).unlink(missing_ok=True)
        return count
    app.cleanup=cleanup
