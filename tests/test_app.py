import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from app import create_app


@pytest.fixture
def app(tmp_path):
    secret=tmp_path/'secret'
    secret.write_text('testing-password-only-123456')
    return create_app(dict(TESTING=True,DATA_DIR=str(tmp_path/'data'),
                           ADMIN_EMAIL='admin@example.com',ADMIN_PASSWORD_FILE=str(secret),
                           SECURE_COOKIES=False,SHARE_LIMIT=1000,STORAGE_LIMIT=1500))


def login(app,email='admin@example.com',password='testing-password-only-123456'):
    c=app.test_client()
    assert c.post('/api/login',json=dict(email=email,password=password)).status_code==200
    token=c.get('/api/me').json['csrf']
    return c,{'X-CSRF-Token':token}


def share(c,h,**kw):
    r=c.post('/api/shares',headers=h,json=dict(title='Bonjour <script> / hello',**kw))
    assert r.status_code==201
    return r.json['id']


def upload(c,h,s,data=b'hello world',name='bonjour.txt'):
    return c.post('/api/shares/'+s+'/files',headers=h,query_string={'name':name},data=data,content_type='application/octet-stream')


def test_roundtrip_password_checksum_and_revocation(app):
    c,h=login(app);s=share(c,h,password='share-secret')
    r=upload(c,h,s);assert r.status_code==201
    fid=r.json['id'];assert r.json['sha256']==hashlib.sha256(b'hello world').hexdigest()
    guest=app.test_client()
    assert guest.get('/api/public/'+s).json['locked']
    assert guest.get(f'/api/public/{s}/files/{fid}').status_code==403
    assert guest.post(f'/api/public/{s}/unlock',json={'password':'wrong'}).status_code==401
    assert guest.post(f'/api/public/{s}/unlock',json={'password':'share-secret'}).status_code==200
    r=guest.get(f'/api/public/{s}/files/{fid}');assert r.data==b'hello world';r.close()
    assert c.delete('/api/shares/'+s,headers=h).status_code==200
    assert guest.get('/api/public/'+s).status_code==404
    assert app.cleanup()==1


def test_cross_owner_csrf_and_traversal(app):
    c,h=login(app)
    assert c.post('/api/users',headers=h,json={'email':'other@example.com','password':'other-user-password-1234'}).status_code==201
    other,oh=login(app,'other@example.com','other-user-password-1234')
    assert other.post('/api/users',headers=oh,json={}).status_code==403
    s=share(c,h)
    assert upload(other,oh,s).status_code==404
    assert other.delete('/api/shares/'+s,headers=oh).status_code==404
    assert upload(c,h,s,name='../secret').status_code==400
    assert upload(c,h,s,name='a\\secret').status_code==400
    assert c.post('/api/shares',json={'title':'no csrf'}).status_code==403
    assert c.post('/api/shares',headers={**h,'Origin':'https://attacker.example'},json={'title':'bad origin'}).status_code==403
    assert app.test_client().get('/api/shares').status_code==401


def test_quota_expiry_cleanup_and_persistence(app):
    c,h=login(app);s=share(c,h)
    assert upload(c,h,s,b'a'*800).status_code==201
    assert upload(c,h,s,b'a'*300).status_code==413
    s2=share(c,h)
    assert upload(c,h,s2,b'b'*800).status_code==413
    with app.db(True) as db:db.execute('UPDATE shares SET expires=? WHERE id=?',(int(time.time())-1,s))
    assert app.test_client().get('/api/public/'+s).status_code==404
    assert app.cleanup()==1
    assert upload(c,h,s2,b'b'*800).status_code==201
    reopened=create_app(dict(app.config))
    again,hh=login(reopened)
    assert again.get('/api/shares').json['used']==800


def test_download_limit_atomic_and_head(app):
    c,h=login(app);s=share(c,h,max_downloads=1);f=upload(c,h,s).json['id']
    url=f'/api/public/{s}/files/{f}'
    head=app.test_client().head(url);assert head.status_code==200;head.close()
    def get_file(_):
        r=app.test_client().get(url);code=r.status_code;r.close();return code
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(get_file,range(2)))
    assert sorted(results)==[200,410]


def test_password_change_invalidates_sessions_and_language(app):
    c,h=login(app)
    assert c.put('/api/me/language',headers=h,json={'language':'fr'}).status_code==200
    assert c.get('/api/me').json['language']=='fr'
    assert c.put('/api/me/password',headers=h,json={'current_password':'testing-password-only-123456','password':'new-password-only-123456'}).status_code==200
    assert c.get('/api/me').status_code==401
    login(app,password='new-password-only-123456')


def test_rate_limit_and_safe_headers(app):
    c=app.test_client()
    assert c.post('/api/login',json=['not','an','object']).status_code==400
    for _ in range(15):assert c.post('/api/login',json={'email':'missing@example.com','password':'incorrect'}).status_code==401
    assert c.post('/api/login',json={}).status_code==429
    r=c.get('/')
    assert r.status_code==200
    assert "frame-ancestors 'none'" in r.headers['Content-Security-Policy']
    assert r.headers['X-Content-Type-Options']=='nosniff'


def test_global_quota_concurrent_reservations(app):
    c,h=login(app);s1=share(c,h);s2=share(c,h)
    session=c.get_cookie('passelio_session').value
    def do_upload(s):
        client=app.test_client();client.set_cookie('passelio_session',session)
        return upload(client,h,s,b'c'*800).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(do_upload,[s1,s2]))
    assert sorted(results)==[201,413]


def test_translation_keys_match():
    # Extract dictionary with Node; both complete locales must remain aligned.
    import subprocess
    from pathlib import Path
    source=(Path(__file__).parents[1]/'static/app.js').read_text(encoding='utf-8').split('let lang=')[0]
    source+=(Path(__file__).parents[1]/'static/admin.js').read_text(encoding='utf-8').split('let adminTab=')[0]
    source+=(Path(__file__).parents[1]/'static/mail.js').read_text(encoding='utf-8').split('let mailConfig=')[0]
    source+=(Path(__file__).parents[1]/'static/system.js').read_text(encoding='utf-8').split('let systemConfig=')[0]
    code=source+'\nconsole.log(JSON.stringify(Object.fromEntries(Object.entries(translations).map(([k,v])=>[k,Object.keys(v).sort()]))));'
    result=subprocess.run(['node','-e',code],capture_output=True,text=True,check=True)
    keys=json.loads(result.stdout)
    assert keys['fr']==keys['en']
    import re
    html=(Path(__file__).parents[1]/'static/index.html').read_text(encoding='utf-8')
    assert set(re.findall(r'data-i18n="([^"]+)"',html)) <= set(keys['fr'])
