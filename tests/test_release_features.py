from test_app import app,login,share
from test_mail import smtp_server,setup_mail


def test_request_notification_is_owner_only_and_upload_only(app,smtp_server):
    c,h=login(app);setup_mail(app,c,h,smtp_server)
    request=c.post('/api/requests',headers=h,json={'title':'Documents','days':1}).json
    sid=request['share_id'];token=request['url'].split('/r/')[1]
    guest=app.test_client()
    assert guest.post('/api/requests/'+sid+'/notify',json={'recipients':['friend@example.com']}).status_code==401
    assert c.post('/api/requests/lookup',headers=h,json={'token':token}).json['share_id']==sid
    assert c.post('/api/requests/'+sid+'/notify',headers=h,json={'recipients':['friend@example.com'],'language':'fr'}).status_code==202
    assert app.process_mail()==1
    message=smtp_server.messages[-1][1]
    plain=message.get_body(preferencelist=('plain',)).get_content()
    assert '/r/'+token in plain and '/s/'+sid not in plain
    assert message.get_body(preferencelist=('html',)) is not None
    assert 'Cc' not in message
    assert c.delete('/api/shares/'+sid,headers=h).status_code==200
    assert c.post('/api/requests/'+sid+'/notify',headers=h,json={'recipients':['friend@example.com']}).status_code==404


def test_admin_share_filters_and_invalid_pages(app):
    c,h=login(app);sid=share(c,h)
    assert c.get('/api/admin/shares?state=active').json['total']==1
    assert c.get('/api/admin/shares?state=revoked').json['total']==0
    assert c.get('/api/admin/shares?page=invalid').status_code==400
    assert c.get('/api/admin/shares?state=invalid').status_code==400
    c.delete('/api/admin/shares/'+sid,headers=h)
    assert c.get('/api/admin/shares?state=revoked').json['total']==1
    assert c.get('/api/admin/shares?state=active').json['total']==0
