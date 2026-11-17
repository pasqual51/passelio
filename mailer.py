"""SMTP notifications: persistent outbox, verified TLS, no secret in API responses."""
import json
import os
import re
import smtplib
import socket
import ssl
import time
from email.message import EmailMessage
from email.utils import formataddr,formatdate
from pathlib import Path
from string import Template

EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z0-9.-]+")
DEFAULT_TEMPLATES = {
    'fr': {'subject': 'Des fichiers vous attendent : ${title}',
           'body': 'Bonjour,\n\n${sender} a partagé des fichiers avec vous.\n\n${title}\n${url}\n\nExpiration (UTC) : ${expiry}\n\nSi un mot de passe est nécessaire, demandez-le à l’expéditeur par un autre canal.\n\nPasselio'},
    'en': {'subject': 'Files are waiting for you: ${title}',
           'body': 'Hello,\n\n${sender} shared files with you.\n\n${title}\n${url}\n\nExpires (UTC): ${expiry}\n\nIf a password is required, ask the sender through a separate channel.\n\nPasselio'}
}


def address(value):
    return isinstance(value, str) and len(value) <= 254 and EMAIL.fullmatch(value) is not None


def addresses(value):
    if not isinstance(value, list) or len(value) > 20 or not all(address(v) for v in value):
        raise ValueError('invalid_input')
    return list(dict.fromkeys(v.lower() for v in value))


def validate_settings(body, allow_plain=False):
    keys={'enabled','host','port','security','username','password','clear_password','from_email','from_name','cc','bcc','templates'}
    if not isinstance(body,dict) or set(body)-keys:
        raise ValueError('invalid_input')
    host=body.get('host','')
    if not isinstance(host,str) or len(host)>253 or not re.fullmatch(r'[A-Za-z0-9._:-]+',host):
        raise ValueError('invalid_input')
    if type(body.get('enabled')) is not bool or type(body.get('port')) is not int or not 1<=body['port']<=65535:
        raise ValueError('invalid_input')
    security=body.get('security')
    if security not in ('starttls','ssl','plain') or (security=='plain' and not allow_plain):
        raise ValueError('smtp_tls_required')
    for key in ('username','from_name'):
        value=body.get(key,'')
        if not isinstance(value,str) or len(value)>254 or any(ord(c)<32 for c in value):
            raise ValueError('invalid_input')
    if not address(body.get('from_email')):
        raise ValueError('invalid_input')
    password=body.get('password','')
    if not isinstance(password,str) or len(password)>1024 or '\x00' in password or type(body.get('clear_password',False)) is not bool:
        raise ValueError('invalid_input')
    templates=body.get('templates',DEFAULT_TEMPLATES)
    if not isinstance(templates,dict) or set(templates)!={'fr','en'}:
        raise ValueError('invalid_template')
    for locale in templates.values():
        if not isinstance(locale,dict) or set(locale)!={'subject','body'}:
            raise ValueError('invalid_template')
        for key,limit in [('subject',200),('body',6000)]:
            value=locale[key]
            if not isinstance(value,str) or not value.strip() or len(value)>limit or (key=='subject' and ('\r' in value or '\n' in value)):
                raise ValueError('invalid_template')
            template=Template(value)
            if not template.is_valid() or set(template.get_identifiers())-{'title','url','expiry','sender'}:
                raise ValueError('invalid_template')
        if 'url' not in Template(locale['body']).get_identifiers():
            raise ValueError('invalid_template')
    result={k:body.get(k,'') for k in ('enabled','host','port','security','username','from_email','from_name')}
    result.update(cc=addresses(body.get('cc',[])),bcc=addresses(body.get('bcc',[])),templates=templates)
    return result,password,body.get('clear_password',False)


def init_mail(app,db,root):
    secret_path=Path(root)/'smtp-password'
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS mail_config(id INTEGER PRIMARY KEY CHECK(id=1),value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS mail_jobs(id INTEGER PRIMARY KEY,owner INTEGER NOT NULL,share_id TEXT,
          recipient TEXT NOT NULL,language TEXT NOT NULL,kind TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',
          attempts INTEGER NOT NULL DEFAULT 0,created INTEGER NOT NULL,updated INTEGER NOT NULL,error TEXT);
        CREATE INDEX IF NOT EXISTS mail_status ON mail_jobs(status,updated);
        ''')

    def settings(c=None):
        if c is None:
            with db() as connection:return settings(connection)
        row=c.execute('SELECT value FROM mail_config WHERE id=1').fetchone()
        if row:return json.loads(row['value'])
        return dict(enabled=False,host='',port=587,security='starttls',username='',from_email='',from_name='Passelio',cc=[],bcc=[],templates=DEFAULT_TEMPLATES)

    def save(config,password,clear=False):
        # Application-owned secret file, excluded from DB/API/audit values.
        if clear:secret_path.unlink(missing_ok=True)
        elif password:
            tmp=secret_path.with_suffix('.new')
            fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
            with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(password)
            os.chmod(tmp,0o600)
            os.replace(tmp,secret_path)
        with db(True) as c:
            c.execute('INSERT INTO mail_config VALUES(1,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value',(json.dumps(config,ensure_ascii=False),))

    def enqueue(c,owner,recipient,language,share_id=None,kind='share'):
        now=int(time.time())
        return c.execute('INSERT INTO mail_jobs(owner,share_id,recipient,language,kind,created,updated) VALUES(?,?,?,?,?,?,?)',(owner,share_id,recipient,language,kind,now,now)).lastrowid

    def process(limit=20):
        processed=0
        for _ in range(limit):
            now=int(time.time())
            with db(True) as c:
                # A worker crash can cause duplicates on retry: delivery is at least once.
                c.execute("UPDATE mail_jobs SET status='failed',error='smtp_interrupted',updated=? WHERE status='sending' AND updated<?",(now,now-300))
                row=c.execute("SELECT * FROM mail_jobs WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
                if not row:break
                job=dict(row);config=settings(c)
                c.execute("UPDATE mail_jobs SET status='sending',attempts=attempts+1,updated=? WHERE id=?",(now,job['id']))
                share=c.execute('SELECT * FROM shares WHERE id=?',(job['share_id'],)).fetchone() if job['share_id'] else None
                account=c.execute('SELECT email,active FROM users WHERE id=?',(job['owner'],)).fetchone()
            error=None
            try:
                if not config['enabled']:raise ValueError('smtp_disabled')
                if not account or not account['active']:raise ValueError('mail_cancelled')
                if job['kind']=='share' and (not share or share['revoked'] or share['expires']<=time.time()):
                    raise ValueError('mail_cancelled')
                msg=EmailMessage()
                msg['From']=formataddr((config['from_name'],config['from_email']))
                msg['To']=job['recipient']
                msg['Date']=formatdate(localtime=False)
                # CC/BCC apply to shares only, never implicitly to a test message.
                cc=config['cc'] if job['kind']=='share' else []
                bcc=config['bcc'] if job['kind']=='share' else []
                if cc:msg['Cc']=', '.join(cc)
                if job['kind']=='test':
                    msg['Subject']='Passelio — Test SMTP' if job['language']=='fr' else 'Passelio — SMTP test'
                    msg.set_content('Test SMTP envoyé par Passelio.' if job['language']=='fr' else 'SMTP test sent by Passelio.')
                else:
                    import datetime
                    values=dict(title=share['title'].replace('\r',' ').replace('\n',' '),url=app.config['BASE_URL'].rstrip('/')+'/s/'+share['id'],sender=account['email'],expiry=datetime.datetime.fromtimestamp(share['expires'],datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'))
                    template=config['templates'][job['language']]
                    msg['Subject']=Template(template['subject']).substitute(values)
                    msg.set_content(Template(template['body']).substitute(values))
                if config['security']=='plain' and not app.config.get('ALLOW_INSECURE_SMTP',False):
                    raise ValueError('smtp_tls_required')
                cls=smtplib.SMTP_SSL if config['security']=='ssl' else smtplib.SMTP
                kwargs={'timeout':15}
                if config['security']=='ssl':kwargs['context']=ssl.create_default_context()
                with cls(config['host'],config['port'],**kwargs) as smtp:
                    smtp.ehlo()
                    if config['security']=='starttls':smtp.starttls(context=ssl.create_default_context());smtp.ehlo()
                    if config['username']:
                        if not secret_path.exists():raise ValueError('smtp_password_missing')
                        smtp.login(config['username'],secret_path.read_text(encoding='utf-8'))
                    recipients=list(dict.fromkeys([job['recipient']]+cc+bcc))
                    refused=smtp.send_message(msg,from_addr=config['from_email'],to_addrs=recipients)
                    if refused:raise ValueError('smtp_partial')
            except ssl.SSLCertVerificationError:error='smtp_certificate'
            except ssl.SSLError:error='smtp_tls'
            except smtplib.SMTPAuthenticationError:error='smtp_auth'
            except smtplib.SMTPSenderRefused:error='smtp_sender'
            except smtplib.SMTPRecipientsRefused:error='smtp_recipient'
            except smtplib.SMTPDataError:error='smtp_rejected'
            except smtplib.SMTPNotSupportedError:error='smtp_tls_required'
            except (socket.timeout,TimeoutError):error='smtp_timeout'
            except (ConnectionError,OSError):error='smtp_connection'
            except ValueError as exc:error=str(exc) if str(exc) in {'smtp_disabled','mail_cancelled','smtp_password_missing','smtp_partial','smtp_tls_required'} else 'smtp_error'
            except Exception:error='smtp_error'
            with db(True) as c:
                c.execute('UPDATE mail_jobs SET status=?,error=?,updated=? WHERE id=?',('failed' if error else 'sent',error,int(time.time()),job['id']))
                c.execute('INSERT INTO audit(created,user_id,action,target) VALUES(?,?,?,?)',(int(time.time()),job['owner'],'mail.failed' if error else 'mail.sent',str(job['id'])))
            processed+=1
        return processed

    app.mail_settings=settings
    app.save_mail=save
    app.enqueue_mail=enqueue
    app.process_mail=process
    app.smtp_password_present=lambda:secret_path.is_file()
