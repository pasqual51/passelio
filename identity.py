"""Explicit Microsoft/Google OIDC linking, PKCE, state/nonce and local MFA."""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time

from authlib.integrations.requests_client import OAuth2Session
from flask import g,jsonify,request,redirect
from joserfc import jwt
from joserfc.jwk import KeySet
import requests


def init_identity(app,db,root,protected,fail,audit,rate_limit):
    folder=Path(root)/'oidc-secrets';folder.mkdir(mode=0o700,exist_ok=True)
    with db() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS identity_config(provider TEXT PRIMARY KEY,value TEXT NOT NULL,revision TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS identities(provider TEXT,issuer TEXT,subject TEXT,user_id INTEGER NOT NULL REFERENCES users(id),
            PRIMARY KEY(provider,issuer,subject),UNIQUE(provider,user_id));
          CREATE TABLE IF NOT EXISTS oidc_flows(state_hash TEXT PRIMARY KEY,cookie_hash TEXT NOT NULL,provider TEXT NOT NULL,
            nonce TEXT NOT NULL,verifier TEXT NOT NULL,expires INTEGER NOT NULL,revision TEXT NOT NULL,session_hash TEXT,link_user INTEGER);
          CREATE TABLE IF NOT EXISTS oidc_pending(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL,csrf TEXT NOT NULL,expires INTEGER NOT NULL);
        ''')
    def config(provider,c=None):
        if provider not in ('google','microsoft'):return None
        if c is None:
            with db() as c:return config(provider,c)
        row=c.execute('SELECT * FROM identity_config WHERE provider=?',(provider,)).fetchone()
        if not row:return dict(enabled=False,client_id='',tenant_id='',revision='none')
        return {**json.loads(row['value']),'revision':row['revision']}

    def endpoints(provider,cfg):
        if provider=='google':return dict(issuer='https://accounts.google.com',authorization='https://accounts.google.com/o/oauth2/v2/auth',token='https://oauth2.googleapis.com/token',jwks='https://www.googleapis.com/oauth2/v3/certs')
        prefix='https://login.microsoftonline.com/'+cfg['tenant_id']
        return dict(issuer=prefix+'/v2.0',authorization=prefix+'/oauth2/v2.0/authorize',token=prefix+'/oauth2/v2.0/token',jwks=prefix+'/discovery/v2.0/keys')

    def client(provider,cfg):
        return OAuth2Session(cfg['client_id'],Path(cfg['secret_file']).read_text(encoding='utf-8'),scope='openid email profile',
            redirect_uri=app.system_settings()['application_url']+'/auth/'+provider+'/callback',
            token_endpoint_auth_method='client_secret_post',code_challenge_method='S256')

    @app.get('/api/identity/options')
    def identity_options():return jsonify(providers=[p for p in ('google','microsoft') if config(p)['enabled']])

    @app.get('/api/admin/identity')
    @protected(admin=True)
    def get_identity_config():
        result={}
        for provider in ('google','microsoft'):
            value=config(provider)
            result[provider]={k:value.get(k,'') for k in ('enabled','client_id','tenant_id','revision')}
            result[provider]['has_secret']=bool(value.get('secret_file'))
            result[provider]['callback']=app.system_settings()['application_url']+'/auth/'+provider+'/callback'
        return jsonify(result)

    @app.put('/api/admin/identity/<provider>')
    @protected(admin=True)
    def save_identity_config(provider):
        if provider not in ('google','microsoft'):return fail('invalid_input')
        b=request.get_json(silent=True) or {};enabled=b.get('enabled');cid=b.get('client_id','');tenant=b.get('tenant_id','');secret=b.get('client_secret','')
        if type(enabled) is not bool or any(not isinstance(v,str) or len(v)>4096 or '\n' in v or '\r' in v for v in (cid,tenant,secret)):return fail('invalid_input')
        if enabled and (not cid or (provider=='microsoft' and not re.fullmatch(r'[a-fA-F0-9-]{36}',tenant))):return fail('invalid_input')
        error=app.require_reauthentication(b,'identity-config')
        if error:return error
        current=config(provider);path=None;committed=False
        try:
            secret_path=current.get('secret_file')
            if secret:
                path=folder/secrets.token_hex(24)
                with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w',encoding='utf-8') as out:out.write(secret)
                secret_path=str(path)
            if enabled and not secret_path:return fail('invalid_input')
            with db(True) as c:
                if config(provider,c)['revision']!=b.get('revision'):return fail('storage_config_changed',409)
                linked=c.execute('SELECT 1 FROM identities WHERE provider=? LIMIT 1',(provider,)).fetchone()
                if linked and current['client_id'] and (current['client_id']!=cid or current.get('tenant_id','')!=tenant):return fail('identity_in_use',409)
                value=dict(enabled=enabled,client_id=cid,tenant_id=tenant,secret_file=secret_path)
                c.execute('INSERT INTO identity_config VALUES(?,?,?) ON CONFLICT(provider) DO UPDATE SET value=excluded.value,revision=excluded.revision',(provider,json.dumps(value),secrets.token_hex(16)))
                audit(c,'identity.configured',provider)
            committed=True
            return jsonify(ok=True)
        finally:
            if path and not committed:path.unlink(missing_ok=True)

    def begin(provider,uid=None):
        cfg=config(provider)
        if not cfg or not cfg['enabled']:return fail('identity_disabled',404)
        if not rate_limit('oidc-start:'+(request.remote_addr or 'unknown'),10):return fail('rate_limited',429)
        state,cookie,nonce,verifier=(secrets.token_urlsafe(32) for _ in range(4))
        with db(True) as c:
            session_hash=hashlib.sha256(request.cookies.get('passelio_session','').encode()).hexdigest() if uid else None
            c.execute('INSERT INTO oidc_flows VALUES(?,?,?,?,?,?,?,?,?)',(hashlib.sha256(state.encode()).hexdigest(),hashlib.sha256(cookie.encode()).hexdigest(),provider,nonce,verifier,int(time.time())+600,cfg['revision'],session_hash,uid))
        oauth=client(provider,cfg)
        try:url,_=oauth.create_authorization_url(endpoints(provider,cfg)['authorization'],state=state,nonce=nonce,code_verifier=verifier,prompt='select_account')
        finally:oauth.close()
        response=jsonify(url=url) if uid else redirect(url)
        response.set_cookie('passelio_oidc',cookie,max_age=600,secure=app.config['SECURE_COOKIES'],httponly=True,samesite='Lax',path='/auth/')
        return response

    @app.get('/auth/<provider>/start')
    def identity_start(provider):return begin(provider)

    @app.get('/api/me/identities')
    @protected()
    def my_identities():
        with db() as c:return jsonify(providers=[r['provider'] for r in c.execute('SELECT provider FROM identities WHERE user_id=?',(g.user['id'],))])

    @app.post('/api/me/identities/<provider>/link')
    @protected()
    def link_identity(provider):
        error=app.require_reauthentication(request.get_json(silent=True) or {},'identity-link')
        if error:return error
        return begin(provider,g.user['id'])

    @app.delete('/api/me/identities/<provider>')
    @protected()
    def unlink_identity(provider):
        error=app.require_reauthentication(request.get_json(silent=True) or {},'identity-link')
        if error:return error
        with db(True) as c:
            c.execute('DELETE FROM identities WHERE provider=? AND user_id=?',(provider,g.user['id']))
            audit(c,'identity.unlinked',provider)
        return jsonify(ok=True)

    key_cache={}
    def verified_claims(provider,cfg,token,nonce):
        ep=endpoints(provider,cfg);now=time.time()
        def fetch_keys():
            response=requests.get(ep['jwks'],timeout=15);response.raise_for_status()
            if len(response.content)>1024**2:raise ValueError('Key set too large')
            keys=KeySet.import_key_set(response.json());key_cache[ep['issuer']]=(now,keys);return keys
        cached=key_cache.get(ep['issuer']);keys=cached[1] if cached and now-cached[0]<300 else fetch_keys()
        try:decoded=jwt.decode(token['id_token'],keys,algorithms=['RS256'])
        except Exception:decoded=jwt.decode(token['id_token'],fetch_keys(),algorithms=['RS256'])
        registry=jwt.JWTClaimsRegistry(leeway=60,iss={'essential':True,'value':ep['issuer']},aud={'essential':True,'value':cfg['client_id']},
            exp={'essential':True},iat={'essential':True},sub={'essential':True},nonce={'essential':True,'value':nonce})
        registry.validate(decoded.claims);claims=decoded.claims
        if not isinstance(claims['sub'],str) or not 1<=len(claims['sub'])<=255:raise ValueError('Invalid subject')
        if (isinstance(claims['aud'],list) and len(claims['aud'])>1) or 'azp' in claims:
            if claims.get('azp')!=cfg['client_id']:raise ValueError('Invalid authorized party')
        if 'at_hash' in claims:
            digest=base64.urlsafe_b64encode(hashlib.sha256(token['access_token'].encode()).digest()[:16]).rstrip(b'=').decode()
            if not isinstance(claims['at_hash'],str) or not hmac.compare_digest(claims['at_hash'],digest):raise ValueError('Invalid access token hash')
        return claims

    def issue_session(c,uid):
        token,csrf=secrets.token_urlsafe(32),secrets.token_urlsafe(32);duration=app.system_settings(c)['session_hours']*3600
        c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),uid,csrf,int(time.time())+duration))
        return token,duration
    def session_cookie(response,token,duration):
        response.set_cookie('passelio_session',token,max_age=duration,secure=app.config['SECURE_COOKIES'],httponly=True,samesite='Strict')
        return response

    @app.get('/auth/<provider>/callback')
    def identity_callback(provider):
        status='failed';session=None;pending_token=None
        try:
            state=request.args.get('state','');cookie=request.cookies.get('passelio_oidc','')
            if len(state)>128 or len(cookie)>128 or not rate_limit('oidc-callback:'+(request.remote_addr or 'unknown'),20):raise ValueError()
            with db(True) as c:
                flow=c.execute('SELECT * FROM oidc_flows WHERE state_hash=? AND provider=? AND expires>?',(hashlib.sha256(state.encode()).hexdigest(),provider,time.time())).fetchone()
                if not flow or not hmac.compare_digest(flow['cookie_hash'],hashlib.sha256(cookie.encode()).hexdigest()):raise ValueError()
                flow=dict(flow);c.execute('DELETE FROM oidc_flows WHERE state_hash=?',(flow['state_hash'],))
            cfg=config(provider)
            if not cfg or not cfg['enabled'] or cfg['revision']!=flow['revision'] or not request.args.get('code'):raise ValueError()
            oauth=client(provider,cfg)
            try:token=oauth.fetch_token(endpoints(provider,cfg)['token'],code=request.args['code'],code_verifier=flow['verifier'],timeout=15)
            finally:oauth.close()
            claims=verified_claims(provider,cfg,token,flow['nonce']);issuer=endpoints(provider,cfg)['issuer']
            with db(True) as c:
                if config(provider,c)['revision']!=flow['revision']:raise ValueError()
                if flow['link_user']:
                    u=c.execute('SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE u.id=? AND u.active=1 AND s.token=? AND s.expires>?',(flow['link_user'],flow['session_hash'],time.time())).fetchone()
                    if not u:raise ValueError()
                    g.user=dict(u)
                    c.execute('INSERT INTO identities VALUES(?,?,?,?)',(provider,issuer,claims['sub'],u['id']))
                    audit(c,'identity.linked',provider);status='linked'
                else:
                    u=c.execute('SELECT u.* FROM identities i JOIN users u ON u.id=i.user_id WHERE i.provider=? AND i.issuer=? AND i.subject=? AND u.active=1 AND u.email_verified=1',(provider,issuer,claims['sub'])).fetchone()
                    if not u:status='not_linked'
                    else:
                        g.user=dict(u)
                        if c.execute('SELECT 1 FROM mfa_factors WHERE user_id=? AND enabled=1',(u['id'],)).fetchone():
                            pending_token=secrets.token_urlsafe(32)
                            c.execute('INSERT INTO oidc_pending VALUES(?,?,?,?)',(hashlib.sha256(pending_token.encode()).hexdigest(),u['id'],secrets.token_urlsafe(32),int(time.time())+300))
                            status='pending'
                        else:session=issue_session(c,u['id']);status='ok'
                        audit(c,'identity.login',provider)
        except Exception:status='failed'
        response=redirect('/?oidc='+status);response.delete_cookie('passelio_oidc',path='/auth/')
        if session:session_cookie(response,*session)
        if pending_token:response.set_cookie('passelio_oidc_pending',pending_token,max_age=300,secure=app.config['SECURE_COOKIES'],httponly=True,samesite='Strict',path='/api/oidc/')
        return response

    def pending(c):
        token=request.cookies.get('passelio_oidc_pending','')
        return c.execute('SELECT p.* FROM oidc_pending p JOIN users u ON u.id=p.user_id WHERE p.token_hash=? AND p.expires>? AND u.active=1 AND u.email_verified=1',(hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()

    @app.get('/api/oidc/pending')
    def pending_identity():
        with db() as c:
            row=pending(c)
            if not row:return fail('unauthorized',401)
            return jsonify(csrf=row['csrf'])

    @app.post('/api/oidc/complete')
    def complete_identity():
        if not rate_limit('oidc-mfa:'+(request.remote_addr or 'unknown'),15):return fail('rate_limited',429)
        with db(True) as c:
            row=pending(c)
            if not row:return fail('unauthorized',401)
            if not hmac.compare_digest(request.headers.get('X-CSRF-Token',''),row['csrf']):return fail('csrf',403)
            error=app.verify_mfa_login(row['user_id'],(request.get_json(silent=True) or {}).get('code'),c)
            if error:return fail(error,401)
            session=issue_session(c,row['user_id']);c.execute('DELETE FROM oidc_pending WHERE token_hash=?',(row['token_hash'],))
        response=session_cookie(jsonify(ok=True),*session);response.delete_cookie('passelio_oidc_pending',path='/api/oidc/');return response

    previous=app.cleanup
    def cleanup():
        count=previous()
        with db(True) as c:
            c.execute('DELETE FROM oidc_flows WHERE expires<=?',(time.time(),));c.execute('DELETE FROM oidc_pending WHERE expires<=?',(time.time(),))
        with db() as c:refs={json.loads(r['value']).get('secret_file') for r in c.execute('SELECT value FROM identity_config')}
        for path in folder.iterdir():
            if path.is_file() and not path.is_symlink() and path.name.isalnum() and path.stat().st_mtime<time.time()-7*86400 and str(path) not in refs:path.unlink(missing_ok=True)
        return count
    app.cleanup=cleanup
