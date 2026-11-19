"""Single-use account invitations and recovery, delivered through the outbox."""
import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from pathlib import Path

from flask import g, jsonify, request
from werkzeug.security import generate_password_hash
from mailer import address


def init_accounts(app, db, root, protected, fail, audit, rate_limit):
    key_path = Path(root) / 'account-signing-key'
    if not key_path.exists():
        candidate=key_path.with_name('.account-key-'+secrets.token_hex(12))
        fd=os.open(candidate,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            with os.fdopen(fd,'wb') as f:
                f.write(secrets.token_bytes(32));f.flush();os.fsync(f.fileno())
            try:os.link(candidate,key_path)
            except FileExistsError:pass
        finally:candidate.unlink(missing_ok=True)
    key = key_path.read_bytes()
    if len(key) != 32:
        raise ValueError('Invalid account signing key')
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS account_actions(
          id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id),
          purpose TEXT NOT NULL, expires INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0);
        ''')
        if 'display_name' not in [r['name'] for r in c.execute('PRAGMA table_info(users)')]:
            c.execute("ALTER TABLE users ADD COLUMN display_name TEXT NOT NULL DEFAULT ''")

    def token_for(aid):
        return aid + '.' + hmac.new(key, aid.encode(), hashlib.sha256).hexdigest()

    def issue(c, uid, email, language, purpose):
        aid = secrets.token_hex(24)
        token = token_for(aid)
        c.execute('UPDATE account_actions SET used=1 WHERE user_id=? AND used=0', (uid,))
        c.execute('INSERT INTO account_actions VALUES(?,?,?,?,?,0)',
                  (aid, hashlib.sha256(token.encode()).hexdigest(), uid, purpose,
                   int(time.time()) + (86400 if purpose == 'invite' else 3600)))
        app.enqueue_mail(c, uid, email, language, share_id=aid, kind='account')
        return aid

    app.issue_account_action=issue

    @app.post('/api/account/recover')
    def recover():
        body = request.get_json(silent=True) or {}
        email = body.get('email', '')
        if not isinstance(email, str) or not address(email):
            return fail('invalid_input')
        email = email.strip().lower()
        if not rate_limit('recover-ip:' + (request.remote_addr or 'unknown'), 10):
            return fail('rate_limited', 429)
        allowed = rate_limit('recover-account:' + hashlib.sha256(email.encode()).hexdigest(), 3)
        with db(True) as c:
            u = c.execute('SELECT * FROM users WHERE email=? AND active=1 AND email_verified=1', (email,)).fetchone()
            if u and allowed and app.mail_settings(c)['enabled']:
                issue(c, u['id'], u['email'], 'fr' if body.get('language') == 'fr' else 'en', 'reset')
        # Never reveal account existence or SMTP availability.
        return jsonify(ok=True), 202

    @app.post('/api/admin/invitations')
    @protected(admin=True)
    def invite():
        body = request.get_json(silent=True) or {}
        email = body.get('email', '')
        if not isinstance(email, str) or not address(email):
            return fail('invalid_input')
        if not rate_limit('invite:' + str(g.user['id']), 20):
            return fail('rate_limited', 429)
        try:
            with db(True) as c:
                if not app.mail_settings(c)['enabled']:
                    return fail('smtp_disabled')
                uid = c.execute('INSERT INTO users(email,password) VALUES(?,?)',
                                (email.strip().lower(), generate_password_hash(secrets.token_urlsafe(48)))).lastrowid
                issue(c, uid, email.strip().lower(), 'fr' if body.get('language') == 'fr' else 'en', 'invite')
                audit(c, 'user.invited', str(uid))
        except sqlite3.IntegrityError:
            return fail('already_exists', 409)
        return jsonify(ok=True), 201

    @app.post('/api/account/complete')
    def complete():
        body = request.get_json(silent=True) or {}
        token, password = body.get('token'), body.get('password')
        if not isinstance(token, str) or len(token) > 160 or not isinstance(password, str) or not 14 <= len(password) <= 1024:
            return fail('invalid_input')
        if not rate_limit('account-complete:' + (request.remote_addr or 'unknown'), 15):
            return fail('rate_limited', 429)
        with db(True) as c:
            row = c.execute('SELECT a.* FROM account_actions a JOIN users u ON u.id=a.user_id '
                            "WHERE token_hash=? AND used=0 AND purpose IN ('invite','reset','register') AND expires>? AND u.active=1",
                            (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
            if not row:
                return fail('account_link_invalid', 410)
            c.execute("UPDATE users SET password=?,email_verified=CASE WHEN ? IN ('invite','register') THEN 1 ELSE email_verified END WHERE id=?", (generate_password_hash(password),row['purpose'], row['user_id']))
            c.execute('DELETE FROM sessions WHERE user_id=?', (row['user_id'],))
            c.execute('UPDATE account_actions SET used=1 WHERE user_id=?', (row['user_id'],))
            audit(c, 'user.account_completed', str(row['user_id']))
        return jsonify(ok=True)

    @app.get('/api/me/profile')
    @protected()
    def profile():
        return jsonify(email=g.user['email'], display_name=g.user['display_name'],email_verified=bool(g.user['email_verified']))

    @app.patch('/api/me/profile')
    @protected()
    def save_profile():
        name = (request.get_json(silent=True) or {}).get('display_name')
        if not isinstance(name, str) or len(name) > 100 or any(ord(ch) < 32 for ch in name):
            return fail('invalid_input')
        with db(True) as c:
            c.execute('UPDATE users SET display_name=? WHERE id=?', (name.strip(), g.user['id']))
            audit(c, 'user.profile_updated', str(g.user['id']))
        return jsonify(ok=True)

    def render_account_mail(job):
        with db() as c:
            action = c.execute('SELECT * FROM account_actions WHERE id=? AND user_id=? AND used=0 AND expires>?',
                               (job['share_id'], job['owner'], time.time())).fetchone()
        if not action:
            raise ValueError('mail_cancelled')
        fr = job['language'] == 'fr'
        invite = action['purpose'] == 'invite'
        subject = ('Votre invitation Passelio' if invite else 'Réinitialiser votre mot de passe') if fr else (
            'Your Passelio invitation' if invite else 'Reset your password')
        url = app.system_settings()['application_url'] + ('/#verify=' if action['purpose']=='change_email' else '/#account=') + token_for(action['id'])
        body = ('Choisissez votre mot de passe avec ce lien personnel, à usage unique :\n' if fr else
                'Choose your password using this personal, single-use link:\n') + url
        body += ('\n\nSi vous n’avez rien demandé, ignorez ce message.' if fr else
                 '\n\nIf you did not request this, ignore this message.')
        if hasattr(app,'render_message_template'):
            return app.render_message_template(action['purpose'], job['language'], dict(url=url,title='',sender='',expiry=''))
        return subject, body

    def render_account_html(job):
        with db() as c:
            action=c.execute('SELECT purpose,id FROM account_actions WHERE id=? AND user_id=? AND used=0 AND expires>?',(job['share_id'],job['owner'],time.time())).fetchone()
        if not action:raise ValueError('mail_cancelled')
        url=app.system_settings()['application_url']+('/#verify=' if action['purpose']=='change_email' else '/#account=')+token_for(action['id'])
        return app.render_html_template(action['purpose'],job['language'],dict(url=url,title='',sender='',expiry=''))
    app.render_account_html=render_account_html
    app.render_account_mail = render_account_mail
