"""Opt-in email-owned registration, verified email changes and per-user quotas."""
import hashlib
import json
import secrets
import sqlite3
import time
from flask import g,jsonify,request
from werkzeug.security import generate_password_hash,check_password_hash
from mailer import address


def init_account_policy(app,db,protected,fail,audit,rate_limit):
    with db() as c:
        if 'email_verified' not in {r['name'] for r in c.execute('PRAGMA table_info(users)')}:
            c.execute('ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 1')
        c.executescript('''CREATE TABLE IF NOT EXISTS account_policy(id INTEGER PRIMARY KEY CHECK(id=1),value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS email_changes(action_id TEXT PRIMARY KEY,new_email TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS user_limits(user_id INTEGER PRIMARY KEY REFERENCES users(id),limit_bytes INTEGER NOT NULL);
        ''')

    def policy(c=None):
        if c is None:
            with db() as c:return policy(c)
        row=c.execute('SELECT value FROM account_policy WHERE id=1').fetchone()
        return json.loads(row['value']) if row else {'registration_enabled':False,'domains':[]}
    app.account_policy=policy

    def reauthenticate(body,bucket='account-settings'):
        if not rate_limit(bucket+':'+str(g.user['id']),10):return fail('rate_limited',429)
        password=body.get('current_password')
        if not isinstance(password,str) or len(password)>1024 or not check_password_hash(g.user['password'],password):return fail('invalid_credentials',401)
        with db(True) as c:
            current=c.execute('SELECT password,active FROM users WHERE id=?',(g.user['id'],)).fetchone()
            if not current or not current['active'] or current['password']!=g.user['password']:return fail('invalid_credentials',401)
            error=app.verify_mfa_login(g.user['id'],body.get('mfa_code'),c)
            if error:return fail(error,401)
        return None
    app.require_reauthentication=reauthenticate

    @app.get('/api/account/options')
    def options():
        value=policy()
        return jsonify(registration_enabled=value['registration_enabled'])

    @app.get('/api/admin/account-policy')
    @protected(admin=True)
    def get_policy():return jsonify(policy())

    @app.put('/api/admin/account-policy')
    @protected(admin=True)
    def save_policy():
        b=request.get_json(silent=True) or {};enabled=b.get('registration_enabled');domains=b.get('domains')
        if type(enabled) is not bool or not isinstance(domains,list) or len(domains)>30 or any(not isinstance(x,str) or not address('test@'+x) or x!=x.strip().lower() for x in domains):return fail('invalid_input')
        error=reauthenticate(b,'account-policy')
        if error:return error
        with db(True) as c:
            if enabled and not app.mail_settings(c)['enabled']:return fail('smtp_disabled')
            c.execute('INSERT INTO account_policy VALUES(1,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value',(json.dumps(dict(registration_enabled=enabled,domains=sorted(set(domains)))),))
            audit(c,'account.policy_updated')
        return jsonify(ok=True)

    @app.post('/api/account/register')
    def register():
        b=request.get_json(silent=True) or {};email=b.get('email','')
        if not isinstance(email,str) or not address(email):return fail('invalid_input')
        email=email.strip().lower();value=policy()
        if not value['registration_enabled']:return fail('registration_disabled',403)
        if value['domains'] and email.rsplit('@',1)[1] not in value['domains']:return fail('registration_domain')
        if not rate_limit('register-ip:'+(request.remote_addr or 'unknown'),10):return fail('rate_limited',429)
        allowed=rate_limit('register-email:'+hashlib.sha256(email.encode()).hexdigest(),3)
        # No attacker-chosen credential is ever activated by somebody else's email click.
        hashed=generate_password_hash(secrets.token_urlsafe(48))
        with db(True) as c:
            if not app.mail_settings(c)['enabled']:return fail('smtp_disabled',503)
            row=c.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
            if not row:
                uid=c.execute('INSERT INTO users(email,password,email_verified) VALUES(?,?,0)',(email,hashed)).lastrowid
                row=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
            if allowed and row['active'] and not row['email_verified']:
                app.issue_account_action(c,row['id'],email,'fr' if b.get('language')=='fr' else 'en','register')
        return jsonify(ok=True),202

    @app.post('/api/me/email')
    @protected()
    def change_email():
        b=request.get_json(silent=True) or {};email=b.get('email','')
        if not isinstance(email,str) or not address(email) or email.strip().lower()==g.user['email']:return fail('invalid_input')
        error=reauthenticate(b)
        if error:return error
        email=email.strip().lower()
        with db(True) as c:
            if not app.mail_settings(c)['enabled']:return fail('smtp_disabled')
            if c.execute('SELECT 1 FROM users WHERE email=?',(email,)).fetchone():return fail('already_exists',409)
            aid=app.issue_account_action(c,g.user['id'],email,'fr' if g.user['language']=='fr' else 'en','change_email')
            c.execute('INSERT INTO email_changes VALUES(?,?)',(aid,email))
            audit(c,'user.email_change_requested',str(g.user['id']))
        return jsonify(ok=True),202

    @app.post('/api/account/verify-email')
    def verify_email():
        token=(request.get_json(silent=True) or {}).get('token')
        if not isinstance(token,str) or len(token)>160:return fail('invalid_input')
        if not rate_limit('verify-email:'+(request.remote_addr or 'unknown'),15):return fail('rate_limited',429)
        try:
            with db(True) as c:
                row=c.execute("SELECT a.*,e.new_email,u.email FROM account_actions a JOIN email_changes e ON e.action_id=a.id JOIN users u ON u.id=a.user_id WHERE token_hash=? AND purpose='change_email' AND used=0 AND expires>? AND u.active=1",(hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
                if not row:return fail('account_link_invalid',410)
                c.execute('UPDATE users SET email=?,email_verified=1 WHERE id=?',(row['new_email'],row['user_id']))
                c.execute('UPDATE account_actions SET used=1 WHERE user_id=?',(row['user_id'],))
                c.execute('DELETE FROM sessions WHERE user_id=?',(row['user_id'],))
                app.enqueue_mail(c,row['user_id'],row['email'],'fr' if (request.get_json() or {}).get('language')=='fr' else 'en',kind='email_changed')
                audit(c,'user.email_changed',str(row['user_id']))
        except sqlite3.IntegrityError:return fail('already_exists',409)
        return jsonify(ok=True)

    def quota(c,uid):
        used=c.execute('SELECT coalesce(sum(f.size),0) FROM files f JOIN shares s ON s.id=f.share_id WHERE s.owner=?',(uid,)).fetchone()[0]
        row=c.execute('SELECT limit_bytes FROM user_limits WHERE user_id=?',(uid,)).fetchone()
        return dict(used=used,limit=row['limit_bytes'] if row else None)
    def allowed(c,uid,additional):
        value=quota(c,uid)
        return value['limit'] is None or value['used']+additional<=value['limit']
    app.user_quota=quota;app.user_quota_allows=allowed

    @app.route('/api/admin/users/<int:uid>/quota',methods=['GET','PUT'])
    @protected(admin=True)
    def user_quota(uid):
        with db(True) as c:
            if not c.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone():return fail('not_found',404)
            if request.method=='GET':return jsonify(quota(c,uid))
            value=(request.get_json(silent=True) or {}).get('limit')
            if value is not None and (type(value) is not int or not 1<=value<=2**50):return fail('invalid_input')
            if value is not None and quota(c,uid)['used']>value:return fail('below_usage',409)
            if value is None:c.execute('DELETE FROM user_limits WHERE user_id=?',(uid,))
            else:c.execute('INSERT INTO user_limits VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET limit_bytes=excluded.limit_bytes',(uid,value))
            audit(c,'user.quota_updated',str(uid))
        return jsonify(ok=True)
