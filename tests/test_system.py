import sqlite3
import time
from test_app import app,login,share
from app import create_app


def test_system_settings_persist_and_public_branding(app):
    c,h=login(app)
    changes={'application_name':'My Files','application_url':'https://files.example.test','login_message':'Welcome to our workspace','default_language':'fr'}
    assert c.patch('/api/admin/system',headers=h,json=changes).status_code==200
    public=app.test_client().get('/api/config').json
    assert public['application_name']=='My Files' and 'session_hours' not in public
    reopened=create_app(dict(app.config));other,oh=login(reopened)
    assert other.get('/api/admin/system').json['application_url']=='https://files.example.test'
    r=other.post('/api/shares',headers=oh,json={'title':'Hello'})
    assert r.json['url'].startswith('https://files.example.test/s/')


def test_sharing_policies_are_enforced_by_server(app):
    c,h=login(app)
    assert c.patch('/api/admin/system',headers=h,json={'default_days':3,'max_days':5,'require_share_password':True,'default_downloads':4}).status_code==200
    assert c.post('/api/shares',headers=h,json={'title':'No password'}).json['error']=='share_password_required'
    assert c.post('/api/shares',headers=h,json={'title':'Too long','days':6,'password':'12345678'}).status_code==400
    sid=share(c,h,password='12345678')
    with app.db() as db:
        s=db.execute('SELECT * FROM shares WHERE id=?',(sid,)).fetchone()
        assert 3*86400-5<=s['expires']-time.time()<=3*86400 and s['max_downloads']==4


def test_session_policy_and_admin_guards(app):
    c,h=login(app)
    assert c.patch('/api/admin/system',headers=h,json={'session_hours':1}).status_code==200
    with app.db() as db:assert db.execute('SELECT max(expires) FROM sessions').fetchone()[0]<=time.time()+3601
    c.post('/api/users',headers=h,json={'email':'other@example.com','password':'other-password-123456'})
    other,oh=login(app,'other@example.com','other-password-123456')
    assert other.get('/api/admin/system').status_code==403
    assert other.patch('/api/admin/system',headers=oh,json={'application_name':'bad'}).status_code==403
    assert c.patch('/api/admin/system',json={'application_name':'bad'}).status_code==403
    for changes in [{'application_url':'javascript:bad'},{'application_url':'https://user:pass@example.com'},{'application_url':'https://example.com/path'},{'default_days':31,'max_days':5},{'session_hours':0}]:
        assert c.patch('/api/admin/system',headers=h,json=changes).status_code==400


def test_consistent_database_snapshot_and_copy_settings(app):
    c,h=login(app)
    assert c.patch('/api/admin/mail/copies',headers=h,json={'cc':['si@example.com'],'bcc':[]}).status_code==200
    assert c.get('/api/admin/mail/settings').json['cc']==['si@example.com']
    assert c.post('/api/admin/database-backup').status_code==403
    r=c.post('/api/admin/database-backup',headers=h)
    assert r.status_code==200 and 'attachment' in r.headers['Content-Disposition']
    conn=sqlite3.connect(':memory:')
    conn.deserialize(r.data)
    assert conn.execute('pragma integrity_check').fetchone()[0]=='ok'
    assert conn.execute('SELECT email FROM users').fetchone()[0]=='admin@example.com'
    conn.close()
