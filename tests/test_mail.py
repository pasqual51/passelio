import copy
import smtplib
import socketserver
import ssl
import threading
from email.parser import BytesParser
from email import policy
from unittest.mock import patch

import pytest
from test_app import app,login,share,upload
from mailer import DEFAULT_TEMPLATES


@pytest.fixture
def smtp_server():
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            recipients=[]
            self.wfile.write(b'220 local-test ESMTP\r\n')
            while line:=self.rfile.readline():
                command=line.decode(errors='replace').strip()
                if command.upper().startswith(('EHLO','HELO')):self.wfile.write(b'250 local-test\r\n')
                elif command.upper().startswith('MAIL FROM:'):recipients=[];self.wfile.write(b'250 OK\r\n')
                elif command.upper().startswith('RCPT TO:'):recipients.append(command[8:].strip('<>'));self.wfile.write(b'250 OK\r\n')
                elif command.upper()=='DATA':
                    self.wfile.write(b'354 send data\r\n');data=b''
                    while (part:=self.rfile.readline())!=b'.\r\n':
                        if not part:break
                        data+=part[1:] if part.startswith(b'..') else part
                    self.server.messages.append((recipients,BytesParser(policy=policy.default).parsebytes(data)))
                    self.wfile.write(b'250 accepted\r\n')
                elif command.upper()=='QUIT':self.wfile.write(b'221 bye\r\n');break
                else:self.wfile.write(b'250 OK\r\n')
    server=socketserver.ThreadingTCPServer(('127.0.0.1',0),Handler)
    server.daemon_threads=True;server.messages=[]
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    yield server
    server.shutdown();server.server_close();thread.join()


def config(port,**kwargs):
    result=dict(enabled=True,host='127.0.0.1',port=port,security='plain',username='',password='',from_email='sender@example.com',from_name='Passelio tests',cc=[],bcc=[],templates=copy.deepcopy(DEFAULT_TEMPLATES))
    result.update(kwargs)
    return result


def setup_mail(app,c,h,smtp_server,**kwargs):
    app.config['ALLOW_INSECURE_SMTP']=True
    return c.put('/api/admin/mail/settings',headers=h,json=config(smtp_server.server_address[1],**kwargs))


def test_local_delivery_bcc_hidden_and_bilingual_templates(app,smtp_server):
    c,h=login(app)
    assert setup_mail(app,c,h,smtp_server,cc=['si@example.com'],bcc=['archive@example.com']).status_code==200
    s=share(c,h,password='never-email-this-password');upload(c,h,s)
    for language in ('fr','en'):
        r=c.post('/api/shares/'+s+'/notify',headers=h,json={'recipients':['recipient@example.com'],'language':language})
        assert r.status_code==202
    assert app.process_mail()==2
    assert len(smtp_server.messages)==2
    for recipients,msg in smtp_server.messages:
        assert set(recipients)=={'recipient@example.com','si@example.com','archive@example.com'}
        assert msg['Cc']=='si@example.com' and msg['Bcc'] is None
        body=msg.get_content()
        assert '/s/'+s in body and 'never-email-this-password' not in body
    assert 'Des fichiers' in str(smtp_server.messages[0][1]['Subject'])
    assert 'Files are waiting' in str(smtp_server.messages[1][1]['Subject'])
    assert all(j['status']=='sent' for j in c.get('/api/mail/jobs').json['jobs'])


def test_test_email_is_explicit_and_excludes_automatic_copies(app,smtp_server):
    c,h=login(app)
    setup_mail(app,c,h,smtp_server,cc=['si@example.com'],bcc=['archive@example.com'])
    assert app.process_mail()==0 and not smtp_server.messages
    assert c.post('/api/admin/mail/test',headers=h,json={'recipient':'test@example.com','language':'fr'}).status_code==202
    assert app.process_mail()==1
    recipients,msg=smtp_server.messages[0]
    assert recipients==['test@example.com'] and msg['Cc'] is None and msg['Bcc'] is None


def test_secrets_tls_and_header_validation(app,smtp_server):
    c,h=login(app)
    # Plaintext is refused by default, even for an administrator.
    assert c.put('/api/admin/mail/settings',headers=h,json=config(25)).status_code==400
    cfg=config(587,security='starttls',username='smtp-user',password='secret-do-not-return')
    assert c.put('/api/admin/mail/settings',headers=h,json=cfg).status_code==200
    result=c.get('/api/admin/mail/settings').json
    assert result['has_password'] and 'password' not in result and 'secret-do-not-return' not in str(result)
    cfg['password']='';c.put('/api/admin/mail/settings',headers=h,json=cfg)
    assert app.smtp_password_present()
    for field,value in [('from_name','bad\r\nBcc: victim@example.com'),('host','smtp://bad/path'),('from_email','a@example.com\r\nbad'),('cc',['invalid'])]:
        bad=copy.deepcopy(cfg);bad[field]=value
        assert c.put('/api/admin/mail/settings',headers=h,json=bad).status_code==400
    bad=copy.deepcopy(cfg);bad['templates']['fr']['body']='Missing link'
    assert c.put('/api/admin/mail/settings',headers=h,json=bad).status_code==400
    cfg['clear_password']=True
    assert c.put('/api/admin/mail/settings',headers=h,json=cfg).status_code==200
    assert not app.smtp_password_present()


@pytest.mark.parametrize('exception,error',[
    (smtplib.SMTPAuthenticationError(535,b'password-secret'),'smtp_auth'),
    (ssl.SSLCertVerificationError('private certificate text'),'smtp_certificate'),
    (smtplib.SMTPSenderRefused(550,b'private detail','sender@example.com'),'smtp_sender'),
    (smtplib.SMTPDataError(550,b'private detail'),'smtp_rejected'),
    (TimeoutError('private detail'),'smtp_timeout')])
def test_safe_error_status_and_manual_retry(app,smtp_server,exception,error):
    c,h=login(app);setup_mail(app,c,h,smtp_server)
    job=c.post('/api/admin/mail/test',headers=h,json={'recipient':'test@example.com'}).json['id']
    with patch('mailer.smtplib.SMTP',side_effect=exception):assert app.process_mail()==1
    row=c.get('/api/admin/mail/jobs').json['jobs'][0]
    assert row['status']=='failed' and row['error']==error and 'private' not in str(row) and 'password-secret' not in str(row)
    assert c.post(f'/api/admin/mail/jobs/{job}/retry',headers=h).status_code==202
    assert app.process_mail()==1
    row=c.get('/api/admin/mail/jobs').json['jobs'][0]
    assert row['status']=='sent' and row['attempts']==2


def test_owner_isolation_csrf_and_revoked_share_cancels_delivery(app,smtp_server):
    c,h=login(app);setup_mail(app,c,h,smtp_server)
    c.post('/api/users',headers=h,json={'email':'other@example.com','password':'other-password-123456'})
    other,oh=login(app,'other@example.com','other-password-123456')
    assert other.get('/api/admin/mail/settings').status_code==403
    assert other.get('/api/admin/mail/jobs').status_code==403
    assert c.post('/api/admin/mail/test',json={'recipient':'test@example.com'}).status_code==403
    s=share(c,h);upload(c,h,s)
    assert other.post('/api/shares/'+s+'/notify',headers=oh,json={'recipients':['test@example.com']}).status_code==404
    c.post('/api/shares/'+s+'/notify',headers=h,json={'recipients':['test@example.com']})
    assert not other.get('/api/mail/jobs').json['jobs']
    c.delete('/api/shares/'+s,headers=h)
    app.process_mail()
    assert not smtp_server.messages
    assert c.get('/api/mail/jobs').json['jobs'][0]['error']=='mail_cancelled'


def test_starttls_certificate_verification_is_not_optional(app):
    c,h=login(app)
    cfg=config(587,security='starttls')
    assert c.put('/api/admin/mail/settings',headers=h,json=cfg).status_code==200
    c.post('/api/admin/mail/test',headers=h,json={'recipient':'test@example.com'})
    with patch('mailer.smtplib.SMTP') as factory:
        factory.return_value.__enter__.return_value.send_message.return_value={}
        app.process_mail()
        context=factory.return_value.__enter__.return_value.starttls.call_args.kwargs['context']
        assert context.verify_mode==ssl.CERT_REQUIRED and context.check_hostname
