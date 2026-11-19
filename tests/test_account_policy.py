import re
import json
from test_app import app,login,share,upload
from test_mail import smtp_server,setup_mail


def token(message,fragment='account'):
    return re.search('#'+fragment+r'=([a-f0-9]+\.[a-f0-9]+)',message.get_body(preferencelist=('plain',)).get_content()).group(1)


def test_registration_email_ownership_domain_policy_and_single_use(app,smtp_server):
    c,h=login(app);setup_mail(app,c,h,smtp_server)
    guest=app.test_client()
    assert guest.post('/api/account/register',json={'email':'new@example.com'}).status_code==403
    assert c.put('/api/admin/account-policy',headers=h,json={'registration_enabled':True,'domains':['example.com'],'current_password':'testing-password-only-123456'}).status_code==200
    assert guest.post('/api/account/register',json={'email':'new@other.example'}).status_code==400
    assert guest.post('/api/account/register',json={'email':'new@example.com','password':'attacker-chosen-password'}).status_code==202
    assert guest.post('/api/login',json={'email':'new@example.com','password':'attacker-chosen-password'}).status_code==401
    assert app.process_mail()==1
    code=token(smtp_server.messages[-1][1])
    assert guest.post('/api/account/complete',json={'token':code,'password':'owner-chosen-password-12345'}).status_code==200
    assert guest.post('/api/account/complete',json={'token':code,'password':'owner-chosen-password-12345'}).status_code==410
    user,uh=login(app,'new@example.com','owner-chosen-password-12345')
    assert user.get('/api/me/profile').json['email_verified']
    response=guest.post('/api/account/register',json={'email':'new@example.com'})
    assert response.status_code==202 and app.process_mail()==0


def test_verified_email_change_preserves_old_address_until_confirmation(app,smtp_server):
    c,h=login(app);setup_mail(app,c,h,smtp_server)
    body={'email':'replacement@example.com','current_password':'testing-password-only-123456'}
    assert c.post('/api/me/email',json=body).status_code==403
    assert c.post('/api/me/email',headers=h,json={**body,'current_password':'wrong'}).status_code==401
    assert c.post('/api/me/email',headers=h,json=body).status_code==202
    assert c.get('/api/me/profile').json['email']=='admin@example.com'
    app.process_mail();message=smtp_server.messages[-1][1]
    assert smtp_server.messages[-1][0]==['replacement@example.com']
    code=token(message,'verify')
    assert app.test_client().post('/api/account/complete',json={'token':code,'password':'must-not-reset-password'}).status_code==410
    assert app.test_client().post('/api/account/verify-email',json={'token':code}).status_code==200
    assert c.get('/api/me').status_code==401
    login(app,'replacement@example.com')
    app.process_mail();assert smtp_server.messages[-1][0]==['admin@example.com']


def test_user_quota_counts_reservations_and_applies_to_upload_requests(app):
    c,h=login(app);sid=share(c,h)
    assert c.put('/api/admin/users/1/quota',headers=h,json={'limit':10}).status_code==200
    assert upload(c,h,sid,data=b'12345678').status_code==201
    assert upload(c,h,sid,data=b'123').status_code==413
    assert c.post(f'/api/shares/{sid}/uploads',headers=h,json={'name':'reserved','size':3}).status_code==413
    assert c.put('/api/admin/users/1/quota',headers=h,json={'limit':5}).status_code==409
    request=c.post('/api/requests',headers=h,json={'title':'request','days':1}).json
    cap=request['url'].split('/r/')[1]
    assert app.test_client().post('/api/requests/'+cap+'/uploads',json={'name':'file','size':3}).status_code==413
    assert c.put('/api/admin/users/1/quota',headers=h,json={'limit':None}).status_code==200


def test_html_alternative_escapes_values_and_sanitizes_templates(app,smtp_server):
    c,h=login(app);setup_mail(app,c,h,smtp_server)
    body={'subject':'Hello ${title}','body':'Open ${url}','html':'<script>alert(1)</script><p onclick="x()">${title}<a href="javascript:alert(1)">Bad</a></p>','heading':'Hello','button':'Open safely','footer':'Private files'}
    assert c.put('/api/admin/templates/invite/en',headers=h,json=body).status_code==200
    assert c.post('/api/admin/invitations',headers=h,json={'email':'invite@example.com','language':'en'}).status_code==201
    app.process_mail();message=smtp_server.messages[-1][1]
    html=message.get_body(preferencelist=('html',)).get_content()
    assert 'script' not in html and 'onclick' not in html and 'javascript:' not in html
    assert 'Open safely' in html and 'Private files' in html and message.get_body(preferencelist=('plain',)) is not None
