import hashlib
import time
import io
import zipfile
from test_app import app, login, share


def test_resumable_roundtrip_offsets_quota_and_paths(app):
    c,h=login(app);sid=share(c,h)
    for name in ('../secret','/absolute','folder//a','C:/a','folder/./a'):
        assert c.post(f'/api/shares/{sid}/uploads',headers=h,json={'name':name,'size':10}).status_code==400
    r=c.post(f'/api/shares/{sid}/uploads',headers=h,json={'name':'folder/bonjour.txt','size':11})
    assert r.status_code==201
    fid=r.json['id'];headers={**h,'Upload-Offset':'0'}
    assert c.patch('/api/uploads/'+fid,headers=headers,data=b'hello ').json['offset']==6
    assert c.patch('/api/uploads/'+fid,headers=headers,data=b'hello ').status_code==409
    assert c.get('/api/uploads/'+fid).json['offset']==6
    assert c.post('/api/uploads/'+fid+'/complete',headers=h).status_code==400
    assert c.patch('/api/uploads/'+fid,headers={**h,'Upload-Offset':'6'},data=b'world').status_code==200
    assert c.post('/api/uploads/'+fid+'/complete',headers=h).json['sha256']==hashlib.sha256(b'hello world').hexdigest()
    result=app.test_client().get(f'/api/public/{sid}/files/{fid}')
    assert result.data==b'hello world';result.close()
    assert c.get('/api/uploads/'+fid).json['completed']
    archive=app.test_client().get(f'/api/public/{sid}/archive')
    assert archive.status_code==200
    with zipfile.ZipFile(io.BytesIO(archive.data)) as z:
        assert z.namelist()==['folder/bonjour.txt']
        assert z.read('folder/bonjour.txt')==b'hello world'
    archive.close()


def test_resumable_authorization_expired_cleanup(app):
    c,h=login(app);sid=share(c,h)
    r=c.post(f'/api/shares/{sid}/uploads',headers=h,json={'name':'file','size':900})
    fid=r.json['id']
    assert c.post(f'/api/shares/{sid}/uploads',headers=h,json={'name':'second','size':200}).status_code==413
    assert c.post('/api/users',headers=h,json={'email':'other@example.com','password':'other-password-123456'}).status_code==201
    other,oh=login(app,'other@example.com','other-password-123456')
    assert other.get('/api/uploads/'+fid).status_code==404
    assert other.patch('/api/uploads/'+fid,headers={**oh,'Upload-Offset':'0'},data=b'x').status_code==404
    with app.db(True) as db:db.execute('UPDATE uploads SET expires=?',(int(time.time())-1,))
    assert app.cleanup()==1
    assert c.get('/api/shares').json['used']==0
