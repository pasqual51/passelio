"""Disposable real-service validation. Never mount a production data directory.

Run in the application image with /qa containing synthetic credentials.json,
admin_password and the independently obtained SFTP host public key (sftp.pub).
SeaweedFS and OpenSSH must be on an isolated Docker network, without host ports.
"""
import datetime
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import sqlite3
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import boto3
from botocore.config import Config
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import paramiko

sys.path.insert(0, '/app')
from app import create_app
from backup import create, verify, restore
from mfa import totp

BASE = Path('/qa')
CREDS = json.loads((BASE/'credentials.json').read_text())
PASSWORD = (BASE/'admin_password').read_text().strip()
ROOT = BASE / ('run-' + str(time.time_ns()))
ROOT.mkdir(mode=0o700)
RESULTS = {}


def app_for(name):
    return create_app(dict(TESTING=True, DATA_DIR=str(ROOT/name),
        BACKUP_DIR=str(ROOT/(name+'-backups')), BASE_URL='http://localhost',
        ADMIN_EMAIL='qa@example.invalid', ADMIN_PASSWORD_FILE=str(BASE/'admin_password'),
        SECURE_COOKIES=False, STORAGE_LIMIT=128*1024**2, SHARE_LIMIT=16*1024**2))


def login(app, code=None):
    client = app.test_client()
    body = dict(email='qa@example.invalid', password=PASSWORD)
    if code is not None: body['code'] = code
    result = client.post('/api/login', json=body)
    assert result.status_code == 200, ('login', result.status_code)
    return client, {'X-CSRF-Token':client.get('/api/me').json['csrf']}


def tls_proxy():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Passelio disposable QA')])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now-datetime.timedelta(minutes=1))
        .not_valid_after(now+datetime.timedelta(hours=2))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'),
            x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
        .sign(key, hashes.SHA256()))
    (ROOT/'ca.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (ROOT/'tls.key').write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    class Proxy(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *args): pass
        def forward(self):
            if self.headers.get('Transfer-Encoding','').lower() == 'chunked':
                chunks = []
                while True:
                    size = int(self.rfile.readline().split(b';')[0],16)
                    if not size:
                        while self.rfile.readline().strip(): pass
                        break
                    chunks.append(self.rfile.read(size)); self.rfile.read(2)
                body = b''.join(chunks)
            else:
                body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            connection = http.client.HTTPConnection('passelio-qa-s3', 8333, timeout=30)
            connection.request(self.command, self.path, body, headers={
                **{k:v for k,v in self.headers.items() if k.lower() not in
                   ('transfer-encoding','content-length')}, 'Content-Length':str(len(body))})
            response = connection.getresponse(); payload = response.read()
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in ('connection','transfer-encoding','content-length','server','date'):
                    self.send_header(key, value)
            length = response.getheader('Content-Length','0') if self.command == 'HEAD' else str(len(payload))
            self.send_header('Content-Length', length); self.end_headers()
            if self.command != 'HEAD': self.wfile.write(payload)
            connection.close()
        do_GET = do_PUT = do_POST = do_DELETE = do_HEAD = forward
    server = ThreadingHTTPServer(('127.0.0.1', 0), Proxy)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(ROOT/'ca.pem', ROOT/'tls.key')
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    os.environ['AWS_CA_BUNDLE'] = str(ROOT/'ca.pem')
    return server


def roundtrip(kind, settings=None):
    app = app_for(kind); client, headers = login(app)
    if settings:
        revision = client.get('/api/admin/storage-configuration').json['revision']
        response = client.put('/api/admin/storage-configuration/'+kind, headers=headers,
            json=dict(settings=settings, revision=revision, current_password=PASSWORD, make_default=True))
        assert response.status_code == 200, ('configure', kind, response.status_code)
        # A second process must load the persisted GUI settings and private secrets.
        second = create_app(app.config)
        assert second.storage.default == kind
    shares = []; expected = {}
    for size in (1024**2, 9*1024**2):
        data = bytes(range(251))*(size//251) + bytes(range(size%251))
        digest = hashlib.sha256(data).hexdigest()
        response = client.post('/api/shares', headers=headers, json={'title':'Disposable '+kind})
        assert response.status_code == 201; sid = response.json['id']; shares.append(sid)
        response = client.post('/api/shares/'+sid+'/uploads', headers=headers,
            json={'name':'folder/payload.bin','size':size})
        assert response.status_code == 201; fid = response.json['id']
        offset = 0
        while offset < size:
            response = client.patch('/api/uploads/'+fid, headers={**headers,'Upload-Offset':str(offset)},
                data=data[offset:offset+8*1024**2], content_type='application/octet-stream')
            assert response.status_code == 200; offset = response.json['offset']
        response = client.post('/api/uploads/'+fid+'/complete', headers=headers)
        assert response.status_code == 200 and response.json['sha256'] == digest, (kind,size,response.status_code,response.json.get('error'))
        response = app.test_client().get('/api/public/'+sid+'/files/'+fid)
        assert response.status_code == 200 and hashlib.sha256(response.data).hexdigest() == digest
        response.close(); expected[fid] = digest
        if kind != 'local': assert not (ROOT/kind/'files'/fid).exists()
    # Exercise the actual scheduling/retention routine used by worker.py, three times.
    response = client.put('/api/admin/backups', headers=headers,
        json={'enabled':True,'interval_hours':24,'retention':2})
    assert response.status_code == 200
    for _ in range(3):
        assert client.post('/api/admin/backups', headers=headers).status_code == 202
        assert app.run_backup_cycle()
    state = client.get('/api/admin/backups').json
    assert len(state['archives']) == 2 and state['settings']['last_error'] is None
    archive = ROOT/(kind+'-backups')/state['archives'][0]['name']
    verify(archive); restored = ROOT/(kind+'-restored'); restore(archive, restored)
    reopened = create_app({**app.config,'DATA_DIR':str(restored),
                          'BACKUP_DIR':str(ROOT/(kind+'-restored-backups'))})
    login(reopened)
    assert reopened.storage.default == 'local'
    for fid, digest in expected.items():
        assert hashlib.sha256((restored/'files'/fid).read_bytes()).hexdigest() == digest
    for sid in shares:
        assert client.delete('/api/shares/'+sid, headers=headers).status_code == 200
    app.cleanup()
    with app.db(True) as connection:
        connection.execute('UPDATE storage_deletions SET created=?',(int(time.time())-120,))
    if kind != 'local': assert app.storage.process_deletions() == 2
    RESULTS[kind] = dict(gui_configuration=True, persisted_reload=True,
        sizes_bytes=[1024**2,9*1024**2], resumable=True, download_sha256=True,
        scheduled_backup=True, retention_two_of_three=True, restore_to_local_sha256=True,
        revoke_cleanup=True)
    print(kind.upper()+' TRANSFERS_BACKUP_RETENTION_RESTORE_CLEANUP_OK', flush=True)
    return app


def mfa_check():
    app = app_for('mfa'); client, headers = login(app)
    response = client.post('/api/me/mfa/setup', headers=headers, json={'password':PASSWORD})
    assert response.status_code == 200; secret = response.json['secret']; step = int(time.time())//30
    response = client.post('/api/me/mfa/enable', headers=headers, json={'code':totp(secret,step)})
    assert response.status_code == 200; codes = response.json['recovery_codes']; assert len(set(codes)) == 10
    body = dict(email='qa@example.invalid',password=PASSWORD)
    assert app.test_client().post('/api/login',json=body).json['error'] == 'mfa_required'
    assert app.test_client().post('/api/login',json={**body,'code':totp(secret,step)}).status_code == 401
    login(app,codes[0])
    assert app.test_client().post('/api/login',json={**body,'code':codes[0]}).status_code == 401
    archive = ROOT/'mfa-full.zip';create(ROOT/'mfa',archive);verify(archive);restore(archive,ROOT/'mfa-restored')
    reopened = create_app({**app.config,'DATA_DIR':str(ROOT/'mfa-restored'),
        'BACKUP_DIR':str(ROOT/'mfa-restored-backups')})
    login(reopened,codes[1])
    # Use the real clock, without mocking verification or advancing server time.
    while int(time.time())//30 <= step: time.sleep(.2)
    code = totp(secret,int(time.time())//30); active, active_headers = login(app,code)
    assert app.test_client().post('/api/login',json={**body,'code':code}).status_code == 401
    response = active.post('/api/me/mfa/disable', headers=active_headers,
        json={'password':PASSWORD,'code':codes[2]})
    assert response.status_code == 200; login(app)
    RESULTS['mfa'] = dict(required=True,totp_real_clock=True,replay_rejected=True,
        recovery_single_use=True,backup_restore=True,disable_reauth=True)
    print('MFA_TOTP_REPLAY_RECOVERY_BACKUP_RESTORE_OK',flush=True)


def main():
    server = tls_proxy()
    try:
        plain = boto3.client('s3', endpoint_url='http://passelio-qa-s3:8333',
            aws_access_key_id=CREDS['access'],aws_secret_access_key=CREDS['secret'],
            region_name='us-east-1',config=Config(connect_timeout=2,read_timeout=5,
                retries={'max_attempts':0},s3={'addressing_style':'path'}))
        for attempt in range(30):
            try: plain.head_bucket(Bucket='passelio-qa');break
            except Exception:
                if attempt == 29: raise
                time.sleep(1)
        roundtrip('local')
        roundtrip('s3',dict(endpoint_url='https://127.0.0.1:'+str(server.server_port),
            bucket='passelio-qa',region='us-east-1',prefix='validation/',addressing_style='path',
            use_iam_role=False,access_key_id=CREDS['access'],secret_access_key=CREDS['secret']))
        assert plain.list_objects_v2(Bucket='passelio-qa',Prefix='validation/').get('KeyCount',0) == 0
        hostkey = ' '.join((BASE/'sftp.pub').read_text().split()[:2])
        app = roundtrip('sftp',dict(host='passelio-qa-sftp',port=22,username='qa',root='/objects',
            server_key=hostkey,auth_method='password',password=CREDS['sftp']))
        backend = app.storage.backends['sftp'];ssh,sftp=backend.connect()
        try: assert sftp.listdir('/objects') == []
        finally: sftp.close();ssh.close()
        # A changed host key must be rejected, rather than automatically trusted.
        from blobstore import SFTP
        bad = ROOT/'wrong-hosts';wrong=paramiko.RSAKey.generate(2048)
        bad.write_text('passelio-qa-sftp '+wrong.get_name()+' '+wrong.get_base64()+'\n')
        try: SFTP({**backend.cfg,'known_hosts_file':str(bad)}).check()
        except paramiko.SSHException: RESULTS['sftp']['wrong_host_key_rejected'] = True
        else: raise AssertionError('Wrong SFTP host key accepted')
        mfa_check()
        (ROOT/'results.json').write_text(json.dumps(RESULTS,indent=2))
        (BASE/'results.json').write_text(json.dumps(RESULTS,indent=2))
        print('ALL_DISPOSABLE_INTEGRATION_CHECKS_PASSED',flush=True)
    finally: server.shutdown();server.server_close()


if __name__ == '__main__': main()
