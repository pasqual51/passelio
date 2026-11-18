from test_app import app,login


def test_upload_only_capability_quota_and_revocation(app):
    c,h=login(app)
    created=c.post('/api/requests',headers=h,json={'title':'Documents','days':7})
    assert created.status_code==201
    token=created.json['url'].split('/r/')[1];sid=created.json['share_id']
    guest=app.test_client();base='/api/requests/'+token
    info=guest.get(base)
    assert info.status_code==200 and 'share_id' not in info.json
    started=guest.post(base+'/uploads',json={'name':'document.txt','size':5})
    assert started.status_code==201
    fid=started.json['id']
    assert guest.patch(base+'/uploads/'+fid,headers={'Upload-Offset':'0'},data=b'hello').status_code==200
    assert guest.post(base+'/uploads/'+fid+'/complete').status_code==200
    assert guest.get('/api/uploads/'+fid).status_code==401
    assert guest.get('/api/public/'+token).status_code==404
    assert guest.get(base+'/uploads/unknown').status_code==404
    assert guest.post(base+'/uploads',json={'name':'large','size':1001}).status_code==413
    assert c.delete('/api/shares/'+sid,headers=h).status_code==200
    assert guest.get(base).status_code==404
    assert guest.post(base+'/uploads',json={'name':'file','size':5}).status_code==404
