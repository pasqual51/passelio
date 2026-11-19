import hashlib
import re
import time
from test_app import app, login
from test_mail import smtp_server, setup_mail


def test_recovery_single_use_session_revocation_and_no_copies(app, smtp_server):
    c, h = login(app)
    setup_mail(app, c, h, smtp_server, cc=['copy@example.com'])
    guest = app.test_client()
    unknown = guest.post('/api/account/recover', json={'email':'unknown@example.com'})
    known = guest.post('/api/account/recover', json={'email':'admin@example.com','language':'fr'})
    assert known.status_code == unknown.status_code == 202 and known.json == unknown.json
    assert app.process_mail() == 1
    recipients, message = smtp_server.messages[0]
    assert recipients == ['admin@example.com'] and message['Cc'] is None
    token = re.search(r'#account=([a-f0-9]+\.[a-f0-9]+)', message.get_body(preferencelist=('plain',)).get_content()).group(1)
    with app.db() as db:
        row = db.execute('SELECT * FROM account_actions').fetchone()
        assert row['token_hash'] == hashlib.sha256(token.encode()).hexdigest()
        assert token not in str(dict(row))
    body = {'token':token,'password':'new-testing-password-12345'}
    assert guest.post('/api/account/complete', json=body).status_code == 200
    assert c.get('/api/me').status_code == 401
    assert guest.post('/api/account/complete', json=body).status_code == 410
    login(app,password=body['password'])


def test_invite_authorization_expiration_and_profile(app, smtp_server):
    c,h = login(app)
    setup_mail(app,c,h,smtp_server)
    assert c.post('/api/admin/invitations',json={'email':'new@example.com'}).status_code == 403
    assert c.post('/api/admin/invitations',headers=h,json={'email':'new@example.com'}).status_code == 201
    assert c.post('/api/admin/invitations',headers=h,json={'email':'new@example.com'}).status_code == 409
    app.process_mail()
    token = re.search(r'#account=([a-f0-9]+\.[a-f0-9]+)',smtp_server.messages[0][1].get_body(preferencelist=('plain',)).get_content()).group(1)
    guest = app.test_client()
    with app.db(True) as db:
        db.execute('UPDATE account_actions SET expires=?',(int(time.time())-1,))
    assert guest.post('/api/account/complete',json={'token':token,'password':'new-testing-password-12345'}).status_code == 410
    assert c.patch('/api/me/profile',headers=h,json={'display_name':'Pascal'}).status_code == 200
    assert c.get('/api/me/profile').json['display_name'] == 'Pascal'
    assert c.patch('/api/me/profile',headers=h,json={'display_name':'bad\nname'}).status_code == 400


def test_disabled_and_superseded_recovery(app,smtp_server):
    c,h=login(app);setup_mail(app,c,h,smtp_server)
    guest=app.test_client()
    for _ in range(2):
        assert guest.post('/api/account/recover',json={'email':'admin@example.com'}).status_code==202
    assert app.process_mail()==2
    assert len(smtp_server.messages)==1
    with app.db() as db:
        assert db.execute("SELECT error FROM mail_jobs ORDER BY id LIMIT 1").fetchone()[0]=='mail_cancelled'
