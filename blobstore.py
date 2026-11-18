"""Private local/S3/SFTP blobs. Credentials come from operator-mounted files."""
from contextlib import contextmanager
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import time
import threading
from urllib.parse import urlsplit

from flask import jsonify

OID=re.compile(r'^[a-f0-9]{48}$')


class StorageUnavailable(Exception):
    pass


class StorageRevisionChanged(ValueError):
    pass


def secret_file(path):
    if not isinstance(path,str) or not path or not Path(path).is_file():raise ValueError('Storage credential file missing')
    value=Path(path).read_text(encoding='utf-8').rstrip('\r\n')
    if not value or len(value)>16384:raise ValueError('Invalid storage credential file')
    return value


class Local:
    identity={'kind':'local'}
    def __init__(self,root):self.root=Path(root)/'files'
    def put(self,path,oid,size,digest):pass
    def open(self,oid,size):
        path=self.root/oid
        if not path.is_file() or path.stat().st_size!=size:raise StorageUnavailable()
        return path.open('rb')
    def delete(self,oid):(self.root/oid).unlink(missing_ok=True)
    def check(self):return True


class S3:
    def __init__(self,cfg):
        import boto3
        from botocore.config import Config
        allowed={'bucket','region','prefix','endpoint_url','access_key_id_file','secret_access_key_file','session_token_file','use_iam_role','addressing_style'}
        if not isinstance(cfg,dict) or set(cfg)-allowed:raise ValueError('Invalid S3 configuration')
        bucket=cfg.get('bucket','');prefix=cfg.get('prefix','passelio/');endpoint=cfg.get('endpoint_url')
        if not isinstance(bucket,str) or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]',bucket):raise ValueError('Invalid S3 bucket')
        if not isinstance(prefix,str) or not re.fullmatch(r'[a-zA-Z0-9_/-]{0,200}',prefix) or '..' in prefix.split('/') or prefix.startswith('/'):raise ValueError('Invalid S3 prefix')
        if endpoint:
            parsed=urlsplit(endpoint)
            if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):raise ValueError('S3 endpoint must be an HTTPS origin')
        style=cfg.get('addressing_style','auto')
        if style not in ('auto','path','virtual'):raise ValueError('Invalid S3 addressing style')
        self.bucket=bucket;self.prefix=prefix.rstrip('/')+'/' if prefix else ''
        self.identity=dict(kind='s3',endpoint=endpoint or 'aws',bucket=bucket,region=cfg.get('region','us-east-1'),prefix=self.prefix)
        credentials={}
        if not cfg.get('use_iam_role',False):
            credentials=dict(aws_access_key_id=secret_file(cfg.get('access_key_id_file')),aws_secret_access_key=secret_file(cfg.get('secret_access_key_file')))
            if cfg.get('session_token_file'):credentials['aws_session_token']=secret_file(cfg['session_token_file'])
        self.client=boto3.client('s3',endpoint_url=endpoint,region_name=self.identity['region'],
                                 config=Config(signature_version='s3v4',connect_timeout=10,read_timeout=30,retries={'max_attempts':2,'mode':'standard'},
                                               s3={'addressing_style':style},request_checksum_calculation='when_required',response_checksum_validation='when_required'),**credentials)
    def put(self,path,oid,size,digest):
        from boto3.s3.transfer import TransferConfig
        with Path(path).open('rb') as source:
            self.client.upload_fileobj(source,self.bucket,self.prefix+oid,
                ExtraArgs={'ContentType':'application/octet-stream','Metadata':{'sha256':digest}},
                Config=TransferConfig(multipart_threshold=8*1024**2,multipart_chunksize=8*1024**2,use_threads=False))
        if self.client.head_object(Bucket=self.bucket,Key=self.prefix+oid)['ContentLength']!=size:raise StorageUnavailable()
    def open(self,oid,size):
        result=self.client.get_object(Bucket=self.bucket,Key=self.prefix+oid)
        if result['ContentLength']!=size:result['Body'].close();raise StorageUnavailable()
        return result['Body']
    def delete(self,oid):self.client.delete_object(Bucket=self.bucket,Key=self.prefix+oid)
    def check(self):self.client.head_bucket(Bucket=self.bucket);return True


class SftpHandle:
    def __init__(self,stream,sftp,ssh):self.stream,self.sftp,self.ssh=stream,sftp,ssh
    def read(self,size=-1):return self.stream.read(size)
    def close(self):
        try:self.stream.close()
        finally:
            try:self.sftp.close()
            finally:self.ssh.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()


class SFTP:
    def __init__(self,cfg):
        allowed={'host','port','username','root','known_hosts_file','private_key_file','password_file','passphrase_file'}
        if not isinstance(cfg,dict) or set(cfg)-allowed:raise ValueError('Invalid SFTP configuration')
        host=cfg.get('host');port=cfg.get('port',22);user=cfg.get('username');root=cfg.get('root')
        if not isinstance(host,str) or not host or any(ch.isspace() for ch in host) or '/' in host or type(port) is not int or not 1<=port<=65535 or not isinstance(user,str) or not user:raise ValueError('Invalid SFTP address')
        if not isinstance(root,str) or not root.startswith('/') or '\\' in root or '..' in root.split('/') or any(ord(ch)<32 for ch in root):raise ValueError('Invalid SFTP root')
        if not Path(cfg.get('known_hosts_file','')).is_file():raise ValueError('Verified SFTP known_hosts file required')
        if not cfg.get('private_key_file') and not cfg.get('password_file'):raise ValueError('SFTP credential file required')
        if cfg.get('private_key_file') and not Path(cfg['private_key_file']).is_file():raise ValueError('SFTP key file missing')
        self.cfg=cfg;self.root=root.rstrip('/')
        self.identity=dict(kind='sftp',host=host,port=port,username=user,root=self.root or '/')
    def connect(self):
        import paramiko
        ssh=paramiko.SSHClient();ssh.load_host_keys(self.cfg['known_hosts_file']);ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
        try:
            ssh.connect(self.cfg['host'],port=self.cfg.get('port',22),username=self.cfg['username'],
                password=secret_file(self.cfg['password_file']) if self.cfg.get('password_file') else None,
                key_filename=self.cfg.get('private_key_file'),passphrase=secret_file(self.cfg['passphrase_file']) if self.cfg.get('passphrase_file') else None,
                allow_agent=False,look_for_keys=False,timeout=10,banner_timeout=10,auth_timeout=10,channel_timeout=30)
            sftp=ssh.open_sftp();sftp.get_channel().settimeout(30)
            return ssh,sftp
        except Exception:ssh.close();raise
    def put(self,path,oid,size,digest):
        ssh,sftp=self.connect();remote=self.root+'/'+oid
        try:
            with Path(path).open('rb') as src,sftp.open(remote+'.part','wx') as dst:
                sftp.chmod(remote+'.part',0o600)
                while chunk:=src.read(1024**2):dst.write(chunk)
                dst.flush()
            if sftp.stat(remote+'.part').st_size!=size:raise StorageUnavailable()
            sftp.rename(remote+'.part',remote)
        finally:sftp.close();ssh.close()
    def open(self,oid,size):
        ssh,sftp=self.connect()
        try:
            if sftp.stat(self.root+'/'+oid).st_size!=size:raise StorageUnavailable()
            return SftpHandle(sftp.open(self.root+'/'+oid,'rb'),sftp,ssh)
        except Exception:sftp.close();ssh.close();raise
    def delete(self,oid):
        ssh,sftp=self.connect()
        try:
            for suffix in ('','.part'):
                try:sftp.remove(self.root+'/'+oid+suffix)
                except OSError as e:
                    if e.errno!=errno.ENOENT:raise
        finally:sftp.close();ssh.close()
    def check(self):
        import stat
        ssh,sftp=self.connect()
        try:
            if not stat.S_ISDIR(sftp.stat(self.root or '/').st_mode):raise StorageUnavailable()
        finally:sftp.close();ssh.close()
        return True


class BlobStore:
    def __init__(self,root,db,config=None,adapters=None,expected_revision=None):
        self.root=Path(root);self.db=db;self.backends={'local':Local(root)}
        config=config or {'default':'local'}
        if not isinstance(config,dict) or set(config)-{'default','s3','sftp'}:raise ValueError('Invalid storage configuration')
        self.default=config.get('default','local')
        for name,cls in [('s3',S3),('sftp',SFTP)]:
            if name in config:self.backends[name]=cls(config[name])
        if adapters:self.backends.update(adapters)
        if self.default not in self.backends:raise ValueError('Storage backend is not configured')
        with db(True) as c:
            if expected_revision is not None:
                exists=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='storage_settings'").fetchone()
                revision=c.execute('SELECT revision FROM storage_settings WHERE id=1').fetchone() if exists else None
                if (revision['revision'] if revision else 'deployment')!=expected_revision:raise StorageRevisionChanged()
            columns={r['name'] for r in c.execute('PRAGMA table_info(files)')}
            if 'storage' not in columns:c.execute("ALTER TABLE files ADD COLUMN storage TEXT NOT NULL DEFAULT 'local'")
            if 'object_id' not in columns:c.execute('ALTER TABLE files ADD COLUMN object_id TEXT')
            c.execute('CREATE TABLE IF NOT EXISTS storage_bindings(name TEXT PRIMARY KEY,identity TEXT NOT NULL)')
            c.execute('CREATE TABLE IF NOT EXISTS storage_pins(pin TEXT,backend TEXT,object_id TEXT,expires INTEGER NOT NULL,PRIMARY KEY(pin,backend,object_id))')
            c.execute('CREATE TABLE IF NOT EXISTS storage_deletions(backend TEXT,object_id TEXT,created INTEGER NOT NULL,lease INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(backend,object_id))')
            used={r[0] for r in c.execute("SELECT storage FROM files UNION SELECT backend FROM storage_deletions")}
            if used-set(self.backends):raise ValueError('Existing remote data requires its original storage configuration')
            for name,backend in self.backends.items():
                identity=json.dumps(backend.identity,sort_keys=True)
                previous=c.execute('SELECT identity FROM storage_bindings WHERE name=?',(name,)).fetchone()
                if previous and previous['identity']!=identity and name in used:raise ValueError('Cannot change a storage destination while it contains application data')
                c.execute('INSERT INTO storage_bindings VALUES(?,?) ON CONFLICT(name) DO UPDATE SET identity=excluded.identity',(name,identity))
    def ensure_binding(self,c,name):
        previous=c.execute('SELECT identity FROM storage_bindings WHERE name=?',(name,)).fetchone()
        if name not in self.backends or not previous or previous['identity']!=json.dumps(self.backends[name].identity,sort_keys=True):raise StorageUnavailable()

    def queue_delete(self,c,row):
        if row['storage']!='local' and row['object_id']:
            c.execute('INSERT OR IGNORE INTO storage_deletions(backend,object_id,created) VALUES(?,?,?)',(row['storage'],row['object_id'],int(time.time())))
    def allocate(self,c,fid):
        row=c.execute('SELECT * FROM files WHERE id=?',(fid,)).fetchone()
        self.ensure_binding(c,row['storage'])
        self.queue_delete(c,row)
        oid=fid if row['storage']=='local' else secrets.token_hex(24)
        c.execute('UPDATE files SET object_id=? WHERE id=?',(oid,fid))
        return dict(c.execute('SELECT * FROM files WHERE id=?',(fid,)).fetchone())
    def put(self,row,path,digest):
        try:self.backends[row['storage']].put(path,row['object_id'],row['size'],digest)
        except Exception as e:raise StorageUnavailable() from e
    def open(self,row):
        try:
            oid=row['object_id'] or row['id']
            if not OID.fullmatch(oid):raise StorageUnavailable()
            return self.backends[row['storage']].open(oid,row['size'])
        except Exception as e:raise StorageUnavailable() from e
    def process_deletions(self,limit=10):
        processed=0
        for _ in range(limit):
            now=int(time.time())
            with self.db(True) as c:
                row=c.execute('SELECT * FROM storage_deletions WHERE created<=? AND lease<=? ORDER BY created LIMIT 1',(now-60,now)).fetchone()
                if not row:break
                self.ensure_binding(c,row['backend'])
                c.execute('UPDATE storage_deletions SET lease=? WHERE backend=? AND object_id=?',(now+300,row['backend'],row['object_id']))
                c.execute('DELETE FROM storage_pins WHERE expires<=?',(now,))
                if c.execute('SELECT 1 FROM storage_pins WHERE backend=? AND object_id=? AND expires>?',(row['backend'],row['object_id'],now)).fetchone():continue
                # Never delete a published or still-reserved object.
                if c.execute('SELECT 1 FROM files WHERE storage=? AND object_id=?',(row['backend'],row['object_id'])).fetchone():continue
            try:
                if not OID.fullmatch(row['object_id']):raise StorageUnavailable()
                self.backends[row['backend']].delete(row['object_id'])
            except Exception:continue
            with self.db(True) as c:c.execute('DELETE FROM storage_deletions WHERE backend=? AND object_id=?',(row['backend'],row['object_id']))
            processed+=1
        return processed


def configuration(config=None):
    config=config or {}
    if 'STORAGE_CONFIG' in config:return config['STORAGE_CONFIG']
    path=config.get('STORAGE_CONFIG_FILE') or os.getenv('STORAGE_CONFIG_FILE')
    if not path:return {'default':'local'}
    if Path(path).stat().st_size>65536:raise ValueError('Storage configuration too large')
    return json.loads(Path(path).read_text(encoding='utf-8'))


def runtime_configuration(db,config=None):
    with db() as c:
        exists=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='storage_settings'").fetchone()
        row=c.execute('SELECT value,revision FROM storage_settings WHERE id=1').fetchone() if exists else None
    if row:return json.loads(row['value']),row['revision']
    return configuration(config),'deployment'


def init_storage(app,db,root,protected,fail,audit,rate_limit):
    adapters=app.config.get('STORAGE_ADAPTERS') if app.testing else None
    with db() as c:c.execute('CREATE TABLE IF NOT EXISTS storage_settings(id INTEGER PRIMARY KEY CHECK(id=1),value TEXT NOT NULL,revision TEXT NOT NULL)')
    lock=threading.RLock();app._storage_revision=None
    def refresh():
        with lock:
            for _ in range(3):
                cfg,revision=runtime_configuration(db,app.config)
                if revision==app._storage_revision:return
                try:updated=BlobStore(root,db,cfg,adapters,expected_revision=revision)
                except StorageRevisionChanged:continue
                app.storage=updated;app._storage_revision=revision;return
            raise StorageUnavailable()
    app.refresh_storage=refresh
    refresh()
    @app.before_request
    def refresh_storage_configuration():refresh()
    from storage_gui import init_storage_gui
    init_storage_gui(app,db,root,protected,fail,audit,rate_limit)
    @app.errorhandler(StorageUnavailable)
    def unavailable(error):return fail('storage_unavailable',503)
    @app.get('/api/admin/storage-backends')
    @protected(admin=True)
    def storage_backends():
        with db() as c:
            counts={r['storage']:r['count'] for r in c.execute('SELECT storage,count(*) count FROM files GROUP BY storage')}
            pending=c.execute('SELECT count(*) FROM storage_deletions').fetchone()[0]
        return jsonify(default=app.storage.default,backends=[dict(name=k,files=counts.get(k,0)) for k in app.storage.backends],pending_deletions=pending)
    @app.post('/api/admin/storage-backends/<name>/test')
    @protected(admin=True)
    def storage_test(name):
        from flask import g
        if name not in app.storage.backends:return fail('invalid_input')
        if not rate_limit('storage-test:'+str(g.user['id']),5):return fail('rate_limited',429)
        try:app.storage.backends[name].check()
        except Exception:return fail('storage_unavailable',503)
        return jsonify(ok=True)


def storage_for_backup(root):
    import sqlite3
    @contextmanager
    def db(write=False):
        connection=sqlite3.connect(Path(root)/'passelio.sqlite',timeout=30);connection.row_factory=sqlite3.Row
        try:
            if write:connection.execute('BEGIN IMMEDIATE')
            yield connection;connection.commit()
        except Exception:connection.rollback();raise
        finally:connection.close()
    cfg,revision=runtime_configuration(db)
    return BlobStore(root,db,cfg,expected_revision=revision)
