import base64
import hashlib
import json
import time
from urllib.parse import urlsplit,parse_qs
import pytest
from joserfc import jwt
from joserfc.jwk import RSAKey
from identity import OAuth2Session
from test_app import app,login
from test_mfa import enroll


@pytest.fixture
def provider(app,monkeypatch):
    key=RSAKey.generate_key(2048,parameters={'kid':'test-key'})
    state={'nonce':'','sub':'subject-one','iss':'https://accounts.google.com','aud':'test-client','exp':None}
    class Keys:
        content=json.dumps({'keys':[key.as_dict()]}).encode()
        def raise_for_status(self):pass
        def json(self):return json.loads(self.content)
    monkeypatch.setattr('identity.requests.get',lambda *a,**k:Keys())
    def exchange(self,*args,**kwargs):
        assert kwargs['code_verifier']
        claims=dict(iss=state['iss'],sub=state['sub'],aud=state['aud'],nonce=state['nonce'],iat=int(time.time()),exp=state['exp'] or int(time.time())+300,email='admin@example.com',email_verified=True)
        return {'access_token':'test-access','id_token':jwt.encode({'alg':'RS256','kid':'test-key'},claims,key,algorithms=['RS256'])}
    monkeypatch.setattr(OAuth2Session,'fetch_token',exchange)
    c,h=login(app)
    saved=c.put('/api/admin/identity/google',headers=h,json={'enabled':True,'client_id':'test-client','client_secret':'private-test-client-secret','tenant_id':'','revision':'none','current_password':'testing-password-only-123456'})
    assert saved.status_code==200
    return c,h,state


def begin(c,state,url='/auth/google/start',headers=None):
    response=c.post('/api/me/identities/google/link',headers=headers,json={'current_password':'testing-password-only-123456'}) if headers else c.get(url)
    target=response.json['url'] if headers else response.location
    query=parse_qs(urlsplit(target).query);state['nonce']=query['nonce'][0]
    assert query['code_challenge_method']==['S256']
    assert query['scope']==['openid email profile']
    return query['state'][0]


def callback(c,state):return c.get('/auth/google/callback',query_string={'state':state,'code':'test-code'})


def test_microsoft_single_tenant_link_and_sign_in(app,provider):
    c,h,state=provider;tenant='00000000-1111-2222-3333-444444444444'
    state['iss']='https://login.microsoftonline.com/'+tenant+'/v2.0'
    assert c.put('/api/admin/identity/microsoft',headers=h,json={'enabled':True,'client_id':'test-client','client_secret':'test-secret','tenant_id':tenant,'revision':'none','current_password':'testing-password-only-123456'}).status_code==200
    r=c.post('/api/me/identities/microsoft/link',headers=h,json={'current_password':'testing-password-only-123456'})
    query=parse_qs(urlsplit(r.json['url']).query);state['nonce']=query['nonce'][0]
    assert '/'+tenant+'/' in r.json['url']
    assert c.get('/auth/microsoft/callback',query_string={'state':query['state'][0],'code':'test-code'}).location=='/?oidc=linked'
    guest=app.test_client();r=guest.get('/auth/microsoft/start');query=parse_qs(urlsplit(r.location).query);state['nonce']=query['nonce'][0]
    assert guest.get('/auth/microsoft/callback',query_string={'state':query['state'][0],'code':'test-code'}).location=='/?oidc=ok'
    assert guest.get('/api/me').status_code==200


def test_explicit_link_login_and_no_email_based_account_takeover(app,provider):
    c,h,state=provider
    guest=app.test_client();flow=begin(guest,state)
    assert callback(guest,flow).location=='/?oidc=not_linked'
    assert guest.get('/api/me').status_code==401
    flow=begin(c,state,headers=h)
    assert callback(c,flow).location=='/?oidc=linked'
    assert c.get('/api/me/identities').json['providers']==['google']
    guest=app.test_client();flow=begin(guest,state)
    assert callback(guest,flow).location=='/?oidc=ok'
    assert guest.get('/api/me').json['email']=='admin@example.com'
    assert callback(guest,flow).location=='/?oidc=failed'
    cfg=c.get('/api/admin/identity').json
    assert cfg['google']['has_secret'] and 'private-test-client-secret' not in json.dumps(cfg)


@pytest.mark.parametrize('field,value',[('nonce','wrong-nonce'),('iss','https://attacker.invalid'),('aud','wrong-client'),('exp',1)])
def test_bad_token_claims_do_not_authenticate(app,provider,field,value):
    c,h,state=provider;guest=app.test_client();flow=begin(guest,state);state[field]=value
    assert callback(guest,flow).location=='/?oidc=failed'
    assert guest.get('/api/me').status_code==401


def test_oidc_requires_local_mfa_and_csrf_after_provider_verification(app,provider):
    c,h,state=provider;flow=begin(c,state,headers=h);assert callback(c,flow).location=='/?oidc=linked'
    _,_,_,_,codes=enroll(app)
    guest=app.test_client();flow=begin(guest,state)
    assert callback(guest,flow).location=='/?oidc=pending'
    assert guest.get('/api/me').status_code==401
    csrf=guest.get('/api/oidc/pending').json['csrf']
    assert guest.post('/api/oidc/complete',json={'code':codes[0]}).status_code==403
    assert guest.post('/api/oidc/complete',headers={'X-CSRF-Token':csrf},json={'code':codes[0]}).status_code==200
    assert guest.get('/api/me').status_code==200
    assert guest.post('/api/oidc/complete',headers={'X-CSRF-Token':csrf},json={'code':codes[0]}).status_code==401


def test_link_flow_is_bound_to_browser_and_still_active_local_session(app,provider):
    c,h,state=provider;flow=begin(c,state,headers=h)
    assert callback(app.test_client(),flow).location=='/?oidc=failed'
    assert c.post('/api/logout',headers=h).status_code==200
    assert callback(c,flow).location=='/?oidc=failed'
    with app.db() as db:assert db.execute('SELECT count(*) FROM identities').fetchone()[0]==0
