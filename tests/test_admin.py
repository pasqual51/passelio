from test_app import app,login,share,upload
from app import create_app


def test_admin_routes_require_role_and_csrf(app):
    c,h=login(app)
    assert c.post('/api/users',headers=h,json={'email':'member@example.com','password':'member-password-only-1234'}).status_code==201
    member,mh=login(app,'member@example.com','member-password-only-1234')
    for route in ['overview','users','shares','audit']:
        assert member.get('/api/admin/'+route).status_code==403
        assert app.test_client().get('/api/admin/'+route).status_code==401
    assert member.put('/api/admin/settings',headers=mh,json={}).status_code==403
    assert c.patch('/api/admin/users/2',json={'active':False}).status_code==403
    assert c.get('/api/admin/overview').status_code==200


def test_user_lifecycle_sessions_and_self_protection(app):
    c,h=login(app)
    assert c.post('/api/users',headers=h,json={'email':'member@example.com','password':'member-password-only-1234'}).status_code==201
    member,mh=login(app,'member@example.com','member-password-only-1234')
    users=c.get('/api/admin/users').json['users']
    uid=next(u['id'] for u in users if u['email']=='member@example.com')
    assert all('password' not in u and 'csrf' not in u for u in users)
    assert c.patch('/api/admin/users/1',headers=h,json={'active':False}).status_code==409
    assert c.patch('/api/admin/users/1',headers=h,json={'admin':False}).status_code==409
    assert c.patch('/api/admin/users/'+str(uid),headers=h,json={'active':False}).status_code==200
    assert member.get('/api/me').status_code==401
    assert member.post('/api/login',json={'email':'member@example.com','password':'member-password-only-1234'}).status_code==401
    assert c.patch('/api/admin/users/'+str(uid),headers=h,json={'active':True,'admin':True}).status_code==200
    member,mh=login(app,'member@example.com','member-password-only-1234')
    assert member.get('/api/admin/overview').status_code==200
    assert c.patch('/api/admin/users/'+str(uid),headers=h,json={'admin':False}).status_code==200
    assert member.get('/api/admin/overview').status_code==401


def test_admin_quota_persistence_and_revocation(app):
    c,h=login(app)
    s=share(c,h)
    assert upload(c,h,s,b'a'*800).status_code==201
    overview=c.get('/api/admin/overview').json
    assert overview['used']==800 and overview['shares']==1
    assert c.put('/api/admin/settings',headers=h,json={'STORAGE_LIMIT':500,'SHARE_LIMIT':400}).status_code==409
    assert c.put('/api/admin/settings',headers=h,json={'STORAGE_LIMIT':2000,'SHARE_LIMIT':1800}).status_code==200
    # Raising the per-request body limit must take effect in every app instance.
    reopened=create_app(dict(app.config));cc,hh=login(reopened)
    s2=share(cc,hh)
    assert upload(cc,hh,s2,b'b'*1100).status_code==201
    assert cc.get('/api/shares').json['share_limit']==1800
    assert c.get('/api/admin/users?q=admin').json['users'][0]['used']==1900
    assert c.delete('/api/admin/shares/'+s,headers=h).status_code==200
    assert c.get('/api/public/'+s).status_code==404
    assert c.get('/api/admin/overview').json['cleanup_bytes']==800
    events=c.get('/api/admin/audit').json['events']
    assert any(e['action']=='admin.share_revoked' for e in events)
    assert any(e['action']=='settings.updated' for e in events)


def test_old_database_migrates_without_resetting_passwords(app):
    c,h=login(app)
    with app.db(True) as db:
        db.execute('ALTER TABLE users DROP COLUMN active')
    reopened=create_app(dict(app.config))
    cc,hh=login(reopened)
    assert cc.get('/api/admin/users').json['users'][0]['active']==1
