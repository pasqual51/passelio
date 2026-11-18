"""Admin-owned storage settings with private secret files and atomic revisions."""
import base64
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import time

import paramiko
from flask import g, jsonify, request
from werkzeug.security import check_password_hash

from blobstore import S3,SFTP,runtime_configuration,StorageUnavailable


def init_storage_gui(app,db,root,protected,fail,audit,rate_limit):
    folder=Path(root)/'storage-secrets';folder.mkdir(mode=0o700,exist_ok=True)

    def authenticate(body):
        if not rate_limit('storage-config:'+str(g.user['id']),10):return fail('rate_limited',429)
        password=body.get('current_password')
        if not isinstance(password,str) or len(password)>1024 or not check_password_hash(g.user['password'],password):return fail('invalid_credentials',401)
        with db(True) as c:
            current=c.execute('SELECT password,active FROM users WHERE id=?',(g.user['id'],)).fetchone()
            if not current or not current['active'] or current['password']!=g.user['password']:return fail('invalid_credentials',401)
            error=app.verify_mfa_login(g.user['id'],body.get('mfa_code'),c)
            if error:return fail(error,401)
        return None

    def revision(c):
        row=c.execute('SELECT revision FROM storage_settings WHERE id=1').fetchone()
        return row['revision'] if row else 'deployment'

    def guard(c,kind,identity):
        previous=c.execute('SELECT identity FROM storage_bindings WHERE name=?',(kind,)).fetchone()
        used=c.execute('SELECT 1 FROM files WHERE storage=? UNION SELECT 1 FROM storage_deletions WHERE backend=? UNION SELECT 1 FROM storage_pins WHERE backend=? AND expires>? LIMIT 1',
                       (kind,kind,kind,time.time())).fetchone()
        if used and previous and previous['identity']!=json.dumps(identity,sort_keys=True):return False
        return True

    def host_key(cfg):
        if not cfg:return ''
        try:
            keys=paramiko.HostKeys();keys.load(cfg['known_hosts_file'])
            host=cfg['host'] if cfg.get('port',22)==22 else '['+cfg['host']+']:'+str(cfg['port'])
            found=keys.lookup(host)
            if found:
                key=next(iter(found.values()));return key.get_name()+' '+key.get_base64()
        except Exception:pass
        return ''

    @app.get('/api/admin/storage-configuration')
    @protected(admin=True)
    def storage_configuration():
        cfg,rev=runtime_configuration(db,app.config)
        s3=cfg.get('s3',{});sftp=cfg.get('sftp',{})
        return jsonify(revision=rev,default=cfg.get('default','local'),
            s3=dict(configured=bool(s3),endpoint_url=s3.get('endpoint_url',''),region=s3.get('region','us-east-1'),bucket=s3.get('bucket',''),prefix=s3.get('prefix','passelio/'),
                    addressing_style=s3.get('addressing_style','auto'),use_iam_role=s3.get('use_iam_role',False),has_access_key=bool(s3.get('access_key_id_file')),has_secret_key=bool(s3.get('secret_access_key_file')),has_session_token=bool(s3.get('session_token_file'))),
            sftp=dict(configured=bool(sftp),host=sftp.get('host',''),port=sftp.get('port',22),username=sftp.get('username',''),root=sftp.get('root','/passelio'),server_key=host_key(sftp),
                      auth_method='key' if sftp.get('private_key_file') else 'password',has_password=bool(sftp.get('password_file')),has_private_key=bool(sftp.get('private_key_file')),has_passphrase=bool(sftp.get('passphrase_file'))))

    def save(c,cfg,rev):
        c.execute('INSERT INTO storage_settings VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value,revision=excluded.revision',(json.dumps(cfg),rev))

    @app.put('/api/admin/storage-default')
    @protected(admin=True)
    def storage_default():
        body=request.get_json(silent=True) or {}
        if set(body)-{'default','revision','current_password','mfa_code'}:return fail('invalid_input')
        error=authenticate(body)
        if error:return error
        cfg,rev=runtime_configuration(db,app.config);kind=body.get('default')
        if kind not in ('local','s3','sftp') or (kind!='local' and kind not in cfg):return fail('invalid_input')
        try:app.storage.backends[kind].check()
        except Exception:return fail('storage_unavailable',503)
        cfg['default']=kind;new_revision=secrets.token_hex(16)
        with db(True) as c:
            if body.get('revision')!=revision(c) or rev!=revision(c):return fail('storage_config_changed',409)
            save(c,cfg,new_revision);audit(c,'storage.default_changed',kind)
        app.refresh_storage()
        return jsonify(ok=True)

    @app.put('/api/admin/storage-configuration/<kind>')
    @protected(admin=True)
    def storage_configure(kind):
        body=request.get_json(silent=True) or {}
        if kind not in ('s3','sftp') or set(body)-{'settings','revision','make_default','current_password','mfa_code'} or not isinstance(body.get('settings'),dict) or type(body.get('make_default',False)) is not bool:return fail('invalid_input')
        error=authenticate(body)
        if error:return error
        cfg,rev=runtime_configuration(db,app.config)
        if body.get('revision')!=rev:return fail('storage_config_changed',409)
        previous=cfg.get(kind,{})
        stage=folder/secrets.token_hex(16);stage.mkdir(mode=0o700)
        committed=False
        try:
            settings=body['settings']
            allowed=({'endpoint_url','region','bucket','prefix','addressing_style','use_iam_role','access_key_id','secret_access_key','session_token','clear_session_token'} if kind=='s3' else
                     {'host','port','username','root','server_key','auth_method','password','private_key','passphrase','clear_passphrase'})
            if set(settings)-allowed:raise ValueError()
            def private(name,value,old_field=None,required=False,keep=True):
                if not isinstance(value,str) or len(value)>16384:raise ValueError()
                if not value and keep and old_field and previous.get(old_field):value=Path(previous[old_field]).read_text(encoding='utf-8')
                if not value:
                    if required:raise ValueError()
                    return None
                path=stage/name
                with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w',encoding='utf-8') as out:out.write(value)
                return str(path)
            if kind=='s3':
                role=settings.get('use_iam_role',False)
                if type(role) is not bool or type(settings.get('clear_session_token',False)) is not bool:raise ValueError()
                candidate={key:settings.get(key,default) for key,default in [('endpoint_url',''),('region','us-east-1'),('bucket',''),('prefix','passelio/'),('addressing_style','auto')]}
                if any(not isinstance(v,str) or len(v)>1024 for v in candidate.values()):raise ValueError()
                if not candidate['endpoint_url']:candidate.pop('endpoint_url')
                candidate['use_iam_role']=role
                if not role:
                    candidate['access_key_id_file']=private('s3-access',settings.get('access_key_id',''),'access_key_id_file',True)
                    candidate['secret_access_key_file']=private('s3-secret',settings.get('secret_access_key',''),'secret_access_key_file',True)
                    token=private('s3-token',settings.get('session_token',''),'session_token_file',keep=not settings.get('clear_session_token',False))
                    if token:candidate['session_token_file']=token
                adapter=S3(candidate)
            else:
                candidate={key:settings.get(key,default) for key,default in [('host',''),('port',22),('username',''),('root','/passelio')]}
                if any(not isinstance(candidate[k],str) or len(candidate[k])>1024 for k in ('host','username','root')):raise ValueError()
                key=settings.get('server_key','')
                if not isinstance(key,str) or len(key)>16384:raise ValueError()
                key=key.strip()
                if '\n' in key or '\r' in key:raise ValueError()
                if not key:key=host_key(previous)
                parts=key.strip().split()
                if len(parts)<2:raise ValueError()
                if parts[0] not in ('ssh-ed25519','ssh-rsa','ecdsa-sha2-nistp256','ecdsa-sha2-nistp384','ecdsa-sha2-nistp521'):raise ValueError()
                parsed=paramiko.PKey.from_type_string(parts[0],base64.b64decode(parts[1],validate=True))
                if parsed.get_name()=='ssh-rsa' and parsed.get_bits()<2048:raise ValueError()
                host=candidate['host'] if candidate['port']==22 else '['+candidate['host']+']:'+str(candidate['port'])
                candidate['known_hosts_file']=private('known_hosts',host+' '+parsed.get_name()+' '+parsed.get_base64()+'\n')
                method=settings.get('auth_method','password')
                if method=='password':candidate['password_file']=private('sftp-password',settings.get('password',''),'password_file',True)
                elif method=='key':
                    candidate['private_key_file']=private('sftp-key',settings.get('private_key',''),'private_key_file',True)
                    if type(settings.get('clear_passphrase',False)) is not bool:raise ValueError()
                    passphrase=private('sftp-passphrase',settings.get('passphrase',''),'passphrase_file',keep=not settings.get('clear_passphrase',False) and not settings.get('private_key'))
                    if passphrase:candidate['passphrase_file']=passphrase
                    # Parse the key before making any connection. Never return parser errors.
                    pem=Path(candidate['private_key_file']).read_text(encoding='utf-8');phrase=Path(passphrase).read_text(encoding='utf-8').rstrip('\r\n') if passphrase else None
                    valid=False
                    for cls in (paramiko.Ed25519Key,paramiko.ECDSAKey,paramiko.RSAKey):
                        try:
                            loaded=cls.from_private_key(io.StringIO(pem),password=phrase)
                            if loaded.get_name()=='ssh-rsa' and loaded.get_bits()<2048:continue
                            valid=True;break
                        except (ValueError,paramiko.SSHException):continue
                    if not valid:raise ValueError()
                else:raise ValueError()
                adapter=SFTP(candidate)
            with db() as c:
                if not guard(c,kind,adapter.identity):return fail('storage_destination_in_use',409)
            try:adapter.check()
            except Exception:return fail('storage_unavailable',503)
            updated=copy.deepcopy(cfg);updated[kind]=candidate
            if body.get('make_default'):updated['default']=kind
            new_revision=secrets.token_hex(16)
            with db(True) as c:
                if revision(c)!=rev:return fail('storage_config_changed',409)
                if not guard(c,kind,adapter.identity):return fail('storage_destination_in_use',409)
                c.execute('INSERT INTO storage_bindings VALUES(?,?) ON CONFLICT(name) DO UPDATE SET identity=excluded.identity',(kind,json.dumps(adapter.identity,sort_keys=True)))
                save(c,updated,new_revision);audit(c,'storage.configured',kind)
            committed=True
            app.refresh_storage()
            return jsonify(ok=True)
        except (ValueError,TypeError,OSError,KeyError,paramiko.SSHException):return fail('invalid_input')
        except Exception:return fail('storage_unavailable',503)
        finally:
            if not committed:shutil.rmtree(stage)

    previous_cleanup=app.cleanup
    def cleanup():
        count=previous_cleanup()
        cfg,_=runtime_configuration(db,app.config)
        references=[value for section in cfg.values() if isinstance(section,dict) for value in section.values() if isinstance(value,str)]
        for path in folder.iterdir():
            if path.is_dir() and not path.is_symlink() and len(path.name)==32 and all(ch in '0123456789abcdef' for ch in path.name) and path.stat().st_mtime<time.time()-7*86400 and not any(str(path) in value for value in references):
                shutil.rmtree(path)
        return count
    app.cleanup=cleanup
