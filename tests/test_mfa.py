import base64
import hashlib
import time
import io
from urllib.parse import urlsplit,parse_qs
from PIL import Image
import zxingcpp
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from mfa import totp
from test_app import app,login
from backup import create,restore
from app import create_app

PASSWORD='testing-password-only-123456'


def test_setup_qr_decodes_to_exact_provisioning_uri(app):
    c,h=login(app)
    result=c.post('/api/me/mfa/setup',headers=h,json={'password':PASSWORD})
    assert result.status_code==200
    assert result.headers['Cache-Control']=='no-store'
    data=result.json
    assert data['qr_png'].startswith('data:image/png;base64,')
    image=Image.open(io.BytesIO(base64.b64decode(data['qr_png'].split(',',1)[1])))
    decoded=zxingcpp.read_barcode(image)
    assert decoded is not None and decoded.text==data['uri']
    uri=urlsplit(decoded.text);params=parse_qs(uri.query)
    assert uri.scheme=='otpauth' and uri.netloc=='totp'
    assert params['secret']==[data['secret']]
    assert params['digits']==['6'] and params['period']==['30']
    assert 'qr_png' not in c.get('/api/me/mfa').json
    assert c.post('/api/me/mfa/setup',headers=h,json={'password':'wrong'}).status_code==401
    assert app.test_client().post('/api/me/mfa/setup',json={'password':PASSWORD}).status_code==401


def enroll(app):
    c,h=login(app)
    setup=c.post('/api/me/mfa/setup',headers=h,json={'password':PASSWORD})
    assert setup.status_code==200
    secret=setup.json['secret']
    step=int(time.time())//30
    enabled=c.post('/api/me/mfa/enable',headers=h,json={'code':totp(secret,step)})
    assert enabled.status_code==200
    return c,h,secret,step,enabled.json['recovery_codes']


def test_rfc6238_sha1_vectors():
    secret=base64.b32encode(b'12345678901234567890').decode()
    for stamp,expected in [(59,'94287082'),(1111111109,'07081804'),(1111111111,'14050471'),(1234567890,'89005924'),(2000000000,'69279037'),(20000000000,'65353130')]:
        assert totp(secret,stamp//30,digits=8)==expected


def test_mfa_enable_login_replay_recovery_and_disable(app):
    c,h,secret,step,codes=enroll(app)
    assert len(codes)==len(set(codes))==10
    assert c.get('/api/me').status_code==401
    guest=app.test_client();body={'email':'admin@example.com','password':PASSWORD}
    assert guest.post('/api/login',json=body).json['error']=='mfa_required'
    assert guest.post('/api/login',json={**body,'code':totp(secret,step)}).json['error']=='mfa_invalid'
    with patch('mfa.time.time',return_value=(step+1)*30+1):
        assert guest.post('/api/login',json={**body,'code':totp(secret,step+1)}).status_code==200
        assert app.test_client().post('/api/login',json={**body,'code':totp(secret,step+1)}).status_code==401
    recovery=app.test_client()
    assert recovery.post('/api/login',json={**body,'code':codes[0]}).status_code==200
    assert app.test_client().post('/api/login',json={**body,'code':codes[0]}).status_code==401
    csrf={'X-CSRF-Token':recovery.get('/api/me').json['csrf']}
    state=recovery.get('/api/me/mfa').json
    assert state=={'enabled':True,'recovery_remaining':9}
    assert recovery.post('/api/me/mfa/disable',headers=csrf,json={'password':PASSWORD,'code':codes[1]}).status_code==200
    assert guest.get('/api/me').status_code==401
    login(app)
    assert not list((Path(app.config['DATA_DIR'])/'mfa-secrets').iterdir())


def test_mfa_authorization_pending_expiry_and_private_storage(app):
    c,h=login(app)
    assert c.post('/api/me/mfa/setup',json={'password':PASSWORD}).status_code==403
    assert c.post('/api/me/mfa/setup',headers=h,json={'password':'wrong'}).status_code==401
    setup=c.post('/api/me/mfa/setup',headers=h,json={'password':PASSWORD}).json
    with app.db() as db:
        row=dict(db.execute('SELECT * FROM mfa_factors').fetchone())
        assert setup['secret'] not in str(row)
    assert c.get('/static/mfa-secrets/'+row['pending_id']).status_code==404
    with app.db(True) as db:db.execute('UPDATE mfa_factors SET pending_expires=0')
    assert c.post('/api/me/mfa/enable',headers=h,json={'code':totp(setup['secret'],int(time.time())//30)}).status_code==410
    app.cleanup()
    assert not list((Path(app.config['DATA_DIR'])/'mfa-secrets').iterdir())


def test_mfa_parallel_replay_and_backup_restore(app,tmp_path):
    _,_,secret,step,codes=enroll(app)
    body={'email':'admin@example.com','password':PASSWORD,'code':totp(secret,step+1)}
    with patch('mfa.time.time',return_value=(step+1)*30+1):
        with ThreadPoolExecutor(2) as executor:
            statuses=list(executor.map(lambda _:app.test_client().post('/api/login',json=body).status_code,range(2)))
        assert sorted(statuses)==[200,401]
    archive=tmp_path/'mfa-backup.zip';create(app.config['DATA_DIR'],archive)
    restored=tmp_path/'restored';restore(archive,restored)
    reopened=create_app({**app.config,'DATA_DIR':str(restored)})
    result=reopened.test_client().post('/api/login',json={'email':'admin@example.com','password':PASSWORD,'code':codes[0]})
    assert result.status_code==200
    with reopened.db() as db:
        assert len(__import__('json').loads(db.execute('SELECT recovery_hashes FROM mfa_factors').fetchone()[0]))==9


def test_password_recovery_does_not_remove_second_factor(app):
    enroll(app)
    token='test-recovery-token'
    with app.db(True) as db:
        db.execute('INSERT INTO account_actions VALUES(?,?,?,?,?,0)',
                   ('test-action',hashlib.sha256(token.encode()).hexdigest(),1,'reset',int(time.time())+600))
    guest=app.test_client()
    assert guest.post('/api/account/complete',json={'token':token,'password':'replacement-password-123456'}).status_code==200
    result=guest.post('/api/login',json={'email':'admin@example.com','password':'replacement-password-123456'})
    assert result.status_code==401 and result.json['error']=='mfa_required'
