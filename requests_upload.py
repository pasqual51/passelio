"""Expiring upload-only capabilities; recipients cannot download stored files."""
import hashlib
import hmac
from pathlib import Path
from mailer import address
import secrets
import time
from flask import g, jsonify, request


def init_upload_requests(app,db,protected,fail,audit,rate_limit):
    with db() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS upload_requests(
          token_hash TEXT PRIMARY KEY,share_id TEXT UNIQUE NOT NULL REFERENCES shares(id),
          created INTEGER NOT NULL);''')

    def request_token(sid):
        key=(Path(app.config['DATA_DIR'])/'account-signing-key').read_bytes()
        return hmac.new(key,('upload-request:'+sid).encode(),hashlib.sha256).hexdigest()
    def mail_values(sid):
        token=request_token(sid)
        with db() as c:
            row=c.execute('SELECT s.*,u.email FROM shares s JOIN users u ON u.id=s.owner JOIN upload_requests r ON r.share_id=s.id WHERE s.id=? AND r.token_hash=? AND s.revoked=0 AND s.expires>? AND u.active=1',(sid,hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
        if not row:raise ValueError('mail_cancelled')
        return dict(title=row['title'],url=app.system_settings()['application_url']+'/r/'+token,expiry=str(row['expires']),sender=row['email'])
    app.request_mail_values=mail_values

    @app.post('/api/requests/lookup')
    @protected()
    def request_lookup():
        token=(request.get_json(silent=True) or {}).get('token','')
        if not isinstance(token,str) or len(token)>100:return fail('invalid_input')
        with db() as c:row=c.execute('SELECT s.id FROM shares s JOIN upload_requests r ON r.share_id=s.id WHERE r.token_hash=? AND s.owner=?',(hashlib.sha256(token.encode()).hexdigest(),g.user['id'])).fetchone()
        return jsonify(share_id=row['id']) if row else fail('not_found',404)

    @app.post('/api/requests/<sid>/notify')
    @protected()
    def request_notify(sid):
        b=request.get_json(silent=True) or {};recipients=b.get('recipients');language=b.get('language','en')
        if not isinstance(recipients,list) or not 1<=len(recipients)<=20 or any(not isinstance(x,str) or not address(x) for x in recipients) or language not in ('fr','en'):return fail('invalid_input')
        if not rate_limit('request-notify:'+str(g.user['id']),10):return fail('rate_limited',429)
        with db(True) as c:
            row=c.execute('SELECT owner FROM shares WHERE id=?',(sid,)).fetchone()
            if not row or row['owner']!=g.user['id']:return fail('not_found',404)
            if not app.mail_settings(c)['enabled']:return fail('smtp_disabled',409)
            try:mail_values(sid)
            except ValueError:return fail('not_found',404)
            for recipient in sorted(set(recipients)):app.enqueue_mail(c,g.user['id'],recipient,language,sid,kind='request')
            audit(c,'request.notified',sid)
        return jsonify(ok=True),202

    @app.post('/api/requests')
    @protected()
    def create_request():
        b=request.get_json(silent=True) or {}
        title,days=b.get('title'),b.get('days',7)
        if not isinstance(title,str) or not 1<=len(title.strip())<=150 or type(days) is not int or not 1<=days<=app.system_settings()['max_days']:
            return fail('invalid_input')
        if not rate_limit('create-request:'+str(g.user['id']),20):return fail('rate_limited',429)
        sid=secrets.token_urlsafe(24);token=request_token(sid)
        with db(True) as c:
            count=c.execute('SELECT count(*) FROM shares WHERE owner=? AND revoked=0 AND expires>?',(g.user['id'],time.time())).fetchone()[0]
            if count>=100:return fail('share_count',409)
            # The download share ID is deliberately not exposed to contributors.
            c.execute('INSERT INTO shares(id,owner,title,created,expires,max_downloads) VALUES(?,?,?,?,?,0)',
                      (sid,g.user['id'],title.strip(),int(time.time()),int(time.time())+days*86400))
            c.execute('INSERT INTO upload_requests VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),sid,int(time.time())))
            audit(c,'request.created',sid)
        return jsonify(url=app.system_settings()['application_url']+'/r/'+token,share_id=sid),201

    def authorize(token,fid=None):
        if len(token)>100:return None
        with db() as c:
            row=c.execute('SELECT s.* FROM upload_requests r JOIN shares s ON s.id=r.share_id JOIN users u ON u.id=s.owner '
                          'WHERE r.token_hash=? AND s.revoked=0 AND s.expires>? AND u.active=1',
                          (hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
            if not row:return None
            if fid and not c.execute('SELECT 1 FROM files WHERE id=? AND share_id=?',(fid,row['id'])).fetchone():return None
            g.user=dict(c.execute('SELECT * FROM users WHERE id=?',(row['owner'],)).fetchone())
            return dict(row)

    @app.get('/api/requests/<token>')
    def request_info(token):
        row=authorize(token)
        if not row:return fail('not_found',404)
        return jsonify(title=row['title'],expires=row['expires'])

    @app.post('/api/requests/<token>/uploads')
    def request_begin(token):
        row=authorize(token)
        if not row:return fail('not_found',404)
        if not rate_limit('request-upload:'+hashlib.sha256(token.encode()).hexdigest(),200):return fail('rate_limited',429)
        return app.view_functions['begin'].__wrapped__(row['id'])

    @app.route('/api/requests/<token>/uploads/<fid>',methods=['GET','PATCH'])
    def request_chunk(token,fid):
        if not authorize(token,fid):return fail('not_found',404)
        fn='chunk' if request.method=='PATCH' else 'status'
        return app.view_functions[fn].__wrapped__(fid)

    @app.post('/api/requests/<token>/uploads/<fid>/complete')
    def request_finish(token,fid):
        if not authorize(token,fid):return fail('not_found',404)
        return app.view_functions['finish'].__wrapped__(fid)
