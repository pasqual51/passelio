import json
import io
from pathlib import Path
import secrets
import time
import zipfile
import paramiko
import pytest
from app import create_app
from backup import create,restore
from blobstore import StorageUnavailable,SFTP,S3
from mfa import totp
from test_app import app,login

PASSWORD='testing-password-only-123456'


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setattr(SFTP,'check',lambda self:True)
    monkeypatch.setattr(S3,'check',lambda self:True)
    key=paramiko.RSAKey.generate(2048)
    return dict(host='sftp.example.invalid',port=2022,username='passelio',root='/objects',
                server_key=key.get_name()+' '+key.get_base64(),auth_method='password',password='unique-private-sftp-secret')


def payload(c,settings,**kw):
    return dict(settings=settings,revision=c.get('/api/admin/storage-configuration').json['revision'],
                current_password=PASSWORD,make_default=True,**kw)


def test_gui_sftp_persistence_hot_reload_redaction_and_default(app,settings):
    worker=create_app(app.config)
    c,h=login(app)
    assert c.put('/api/admin/storage-configuration/sftp',json=payload(c,settings)).status_code==403
    assert c.put('/api/admin/storage-configuration/sftp',headers=h,json={**payload(c,settings),'current_password':'wrong'}).status_code==401
    assert c.put('/api/admin/storage-configuration/sftp',headers=h,json=payload(c,settings)).status_code==200
    result=c.get('/api/admin/storage-configuration').json
    assert result['default']=='sftp' and result['sftp']['has_password']
    assert result['sftp']['server_key']==settings['server_key']
    assert settings['password'] not in json.dumps(result) and 'password_file' not in json.dumps(result)
    assert app.storage.default=='sftp'
    worker.refresh_storage();assert worker.storage.default=='sftp'
    with app.db() as db:
        stored=db.execute('SELECT value FROM storage_settings').fetchone()[0]
        assert settings['password'] not in stored
        secret=Path(json.loads(stored)['sftp']['password_file'])
    assert secret.read_text()==settings['password']
    body=dict(revision=result['revision'],current_password=PASSWORD,default='local')
    assert c.put('/api/admin/storage-default',headers=h,json=body).status_code==200
    assert app.storage.default=='local'
    other,oh=login(worker)
    assert other.get('/api/admin/storage-backends').json['default']=='local'
    again=create_app(app.config);assert 'sftp' in again.storage.backends and again.storage.default=='local'


def test_gui_secret_keep_failed_test_and_used_destination_guard(app,settings,monkeypatch):
    c,h=login(app)
    assert c.put('/api/admin/storage-configuration/sftp',headers=h,json=payload(c,settings)).status_code==200
    original=app.storage
    preserved={**settings,'password':''}
    assert c.put('/api/admin/storage-configuration/sftp',headers=h,json=payload(c,preserved)).status_code==200
    with app.db() as db:
        cfg=json.loads(db.execute('SELECT value FROM storage_settings').fetchone()[0])
        assert Path(cfg['sftp']['password_file']).read_text()==settings['password']
    # A stale process cannot reserve data against a replaced binding.
    new_host={**preserved,'host':'second.example.invalid'}
    assert c.put('/api/admin/storage-configuration/sftp',headers=h,json=payload(c,new_host)).status_code==200
    with app.db() as db:
        with pytest.raises(StorageUnavailable):original.ensure_binding(db,'sftp')
    sid=secrets.token_hex(24)
    with app.db(True) as db:
        db.execute('INSERT INTO shares(id,owner,title,created,expires,max_downloads) VALUES(?,1,?,?,?,0)',(sid,'reserved',int(time.time()),int(time.time())+600))
        db.execute('INSERT INTO files(id,share_id,name,size,created,storage) VALUES(?,?,?,?,?,?)',(secrets.token_hex(24),sid,'reserved',10,int(time.time()),'sftp'))
    rejected=c.put('/api/admin/storage-configuration/sftp',headers=h,json=payload(c,{**new_host,'root':'/different'}))
    assert rejected.status_code==409 and rejected.json['error']=='storage_destination_in_use'
    revision=c.get('/api/admin/storage-configuration').json['revision']
    def fail(self):raise OSError('do not expose private credentials')
    monkeypatch.setattr(SFTP,'check',fail)
    bad=c.put('/api/admin/storage-configuration/sftp',headers=h,json=payload(c,{**new_host,'password':'replacement-never-saved'}))
    assert bad.status_code==503 and bad.json=={'error':'storage_unavailable'}
    assert c.get('/api/admin/storage-configuration').json['revision']==revision
    assert not any('replacement-never-saved' in p.read_text() for p in (Path(app.config['DATA_DIR'])/'storage-secrets').glob('*/*'))


def test_gui_s3_secret_validation_stale_revision_and_restore(app,settings,tmp_path):
    c,h=login(app)
    cfg=dict(endpoint_url='https://s3.example.invalid',region='us-east-1',bucket='test-private-bucket',prefix='instance/',
             addressing_style='path',use_iam_role=False,access_key_id='test-access-key-private',secret_access_key='test-secret-key-private')
    stale=payload(c,cfg)
    assert c.put('/api/admin/storage-configuration/s3',headers=h,json=stale).status_code==200
    assert c.put('/api/admin/storage-configuration/s3',headers=h,json=stale).status_code==409
    redacted=c.get('/api/admin/storage-configuration').json
    assert redacted['s3']['has_secret_key'] and cfg['secret_access_key'] not in json.dumps(redacted)
    bad={**cfg,'secret_access_key_file':'/etc/passwd'}
    assert c.put('/api/admin/storage-configuration/s3',headers=h,json=payload(c,bad)).status_code==400
    assert c.put('/api/admin/storage-configuration/s3',headers=h,json=payload(c,{**cfg,'endpoint_url':'http://insecure.example'})).status_code==400
    archive=tmp_path/'gui-config.zip';create(app.config['DATA_DIR'],archive,storage=app.storage)
    with zipfile.ZipFile(archive) as z:assert not any('storage-secrets' in name for name in z.namelist())
    target=tmp_path/'restored';restore(archive,target)
    reopened=create_app({**app.config,'DATA_DIR':str(target)})
    assert reopened.storage.default=='local' and set(reopened.storage.backends)=={'local'}


def test_gui_requires_second_factor_and_rejects_key_injection(app,settings):
    c,h=login(app)
    assert c.put('/api/admin/storage-configuration/sftp',headers=h,json=payload(c,{**settings,'server_key':settings['server_key']+'\notherhost ssh-rsa key'})).status_code==400
    assert c.put('/api/admin/storage-configuration/sftp',headers=h,json=payload(c,{**settings,'auth_method':'key','private_key':'not a private key'})).status_code==400
    setup=c.post('/api/me/mfa/setup',headers=h,json={'password':PASSWORD}).json
    step=int(time.time())//30
    codes=c.post('/api/me/mfa/enable',headers=h,json={'code':totp(setup['secret'],step)}).json['recovery_codes']
    guest=app.test_client()
    assert guest.post('/api/login',json={'email':'admin@example.com','password':PASSWORD,'code':codes[0]}).status_code==200
    csrf={'X-CSRF-Token':guest.get('/api/me').json['csrf']}
    no_code=guest.put('/api/admin/storage-configuration/sftp',headers=csrf,json=payload(guest,settings))
    assert no_code.status_code==401 and no_code.json['error']=='mfa_required'
    assert guest.put('/api/admin/storage-configuration/sftp',headers=csrf,json=payload(guest,settings,mfa_code=codes[1])).status_code==200


def test_gui_rejects_concurrent_configuration_overwrite(app,settings,monkeypatch):
    c,h=login(app);body=payload(c,settings)
    def concurrent_change(self):
        with app.db(True) as db:
            db.execute('INSERT INTO storage_settings VALUES(1,?,?)',(json.dumps({'default':'local'}),'changed-concurrently'))
        return True
    monkeypatch.setattr(SFTP,'check',concurrent_change)
    result=c.put('/api/admin/storage-configuration/sftp',headers=h,json=body)
    assert result.status_code==409 and result.json['error']=='storage_config_changed'
    assert c.get('/api/admin/storage-backends').json['default']=='local'


def test_gui_encrypted_ssh_key_and_blank_secret_preservation(app,settings):
    c,h=login(app)
    key=paramiko.RSAKey.generate(2048);pem=io.StringIO()
    key.write_private_key(pem,password='private-key-test-passphrase')
    values={**settings,'auth_method':'key','password':'','private_key':pem.getvalue(),'passphrase':'private-key-test-passphrase','server_key':settings['server_key']+' comment with spaces\n'}
    assert c.put('/api/admin/storage-configuration/sftp',headers=h,json=payload(c,values)).status_code==200
    state=c.get('/api/admin/storage-configuration').json
    assert state['sftp']['has_private_key'] and state['sftp']['has_passphrase']
    assert 'BEGIN RSA PRIVATE KEY' not in json.dumps(state) and values['passphrase'] not in json.dumps(state)
    assert c.put('/api/admin/storage-configuration/sftp',headers=h,json=payload(c,{**values,'private_key':'','passphrase':''})).status_code==200
    assert c.get('/api/admin/storage-configuration').json['sftp']['has_passphrase']
