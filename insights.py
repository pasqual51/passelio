"""Bounded administration statistics and idempotent lifecycle notifications."""
import datetime
import json
import time
from string import Template
from flask import g, jsonify, request

DEFAULTS = {
    'invite': {'en': {'subject':'Your Passelio invitation','body':'Choose your password: ${url}'},
               'fr': {'subject':'Votre invitation Passelio','body':'Choisissez votre mot de passe : ${url}'}},
    'reset': {'en': {'subject':'Reset your password','body':'Use this personal single-use link: ${url}\nIf you did not request this, ignore this message.'},
              'fr': {'subject':'Réinitialiser votre mot de passe','body':'Utilisez ce lien personnel à usage unique : ${url}\nSi vous n’avez rien demandé, ignorez ce message.'}},
    'download': {'en': {'subject':'Your share was downloaded','body':'A download was requested for ${title}.\n${url}'},
                 'fr': {'subject':'Votre partage a été téléchargé','body':'Un téléchargement a été demandé pour ${title}.\n${url}'}},
    'expiring': {'en': {'subject':'Your share expires soon','body':'${title} expires at ${expiry}.\n${url}'},
                 'fr': {'subject':'Votre partage expire bientôt','body':'${title} expire le ${expiry}.\n${url}'}},
    'expired': {'en': {'subject':'Your share expired','body':'${title} has expired. Its link is no longer available.'},
                'fr': {'subject':'Votre partage a expiré','body':'${title} a expiré. Son lien n’est plus accessible.'}},
    'revoked': {'en': {'subject':'Your share was revoked','body':'${title} was revoked. Its link is no longer available.'},
                'fr': {'subject':'Votre partage a été révoqué','body':'${title} a été révoqué. Son lien n’est plus accessible.'}},
}


def init_insights(app,db,protected,fail,audit):
    with db() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS message_templates(kind TEXT,language TEXT,value TEXT,
          PRIMARY KEY(kind,language));
          CREATE TABLE IF NOT EXISTS lifecycle_events(share_id TEXT,kind TEXT,PRIMARY KEY(share_id,kind));
          CREATE TABLE IF NOT EXISTS notification_config(id INTEGER PRIMARY KEY CHECK(id=1),enabled INTEGER NOT NULL);
        ''')

    def template(c,kind,language):
        row=c.execute('SELECT value FROM message_templates WHERE kind=? AND language=?',(kind,language)).fetchone()
        return json.loads(row['value']) if row else DEFAULTS[kind][language]

    def render(kind,language,values):
        with db() as c:choice=template(c,kind,language)
        return (Template(choice['subject']).substitute(values),Template(choice['body']).substitute(values))
    app.render_message_template=render

    @app.get('/api/admin/templates')
    @protected(admin=True)
    def templates():
        with db() as c:
            row=c.execute('SELECT enabled FROM notification_config WHERE id=1').fetchone()
            return jsonify(templates={k:{lang:template(c,k,lang) for lang in ('fr','en')} for k in DEFAULTS},
                           lifecycle_enabled=bool(row and row['enabled']))

    @app.put('/api/admin/templates/<kind>/<language>')
    @protected(admin=True)
    def save_template(kind,language):
        if kind not in DEFAULTS or language not in ('fr','en'):return fail('invalid_input')
        body=request.get_json(silent=True) or {}
        if set(body)!={'subject','body'}:return fail('invalid_input')
        for name,maximum in [('subject',200),('body',10000)]:
            value=body[name]
            if not isinstance(value,str) or not value.strip() or len(value)>maximum or '\r' in value or (name=='subject' and '\n' in value):return fail('invalid_input')
            try:Template(value).substitute(title='Title',url='https://example.invalid/',expiry='Date',sender='sender@example.invalid')
            except (KeyError,ValueError):return fail('invalid_input')
        if kind in ('invite','reset') and '${url}' not in body['body']:return fail('invalid_input')
        with db(True) as c:
            c.execute('INSERT INTO message_templates VALUES(?,?,?) ON CONFLICT(kind,language) DO UPDATE SET value=excluded.value',
                      (kind,language,json.dumps(body)))
            audit(c,'mail.template_updated',kind+':'+language)
        return jsonify(ok=True)

    @app.put('/api/admin/notifications')
    @protected(admin=True)
    def notifications():
        enabled=(request.get_json(silent=True) or {}).get('enabled')
        if type(enabled) is not bool:return fail('invalid_input')
        with db(True) as c:
            c.execute('INSERT INTO notification_config VALUES(1,?) ON CONFLICT(id) DO UPDATE SET enabled=excluded.enabled',(int(enabled),))
            # Activation starts from now; do not send historical notices.
            if enabled:
                for kind,predicate in [('expired','expires<=?'),('revoked','revoked=1 AND created<=?'),('download','downloads>0 AND created<=?')]:
                    c.execute('INSERT OR IGNORE INTO lifecycle_events SELECT id,? FROM shares WHERE '+predicate,(kind,time.time()))
            audit(c,'mail.lifecycle_configured')
        return jsonify(ok=True)

    def schedule(c,s,kind):
        flag=c.execute('SELECT enabled FROM notification_config WHERE id=1').fetchone()
        if not flag or not flag['enabled'] or not app.mail_settings(c)['enabled']:return
        owner=c.execute('SELECT * FROM users WHERE id=? AND active=1',(s['owner'],)).fetchone()
        if not owner:return
        if c.execute('INSERT OR IGNORE INTO lifecycle_events VALUES(?,?)',(s['id'],kind)).rowcount:
            app.enqueue_mail(c,owner['id'],owner['email'],'fr' if owner['language']=='fr' else 'en',s['id'],kind)
    app.schedule_notification=schedule

    def lifecycle_message(job,share,account):
        values=dict(title=share['title'].replace('\r',' ').replace('\n',' '),sender=account['email'],
                    url=app.system_settings()['application_url']+'/s/'+share['id'],
                    expiry=datetime.datetime.fromtimestamp(share['expires'],datetime.timezone.utc).isoformat())
        return render(job['kind'],job['language'],values)
    app.render_lifecycle_mail=lifecycle_message
    previous_cleanup=app.cleanup
    def cleanup():
        with db(True) as c:
            for s in c.execute('SELECT * FROM shares WHERE revoked=1 OR expires<=? ORDER BY created DESC LIMIT 1000',(time.time()+86400,)).fetchall():
                schedule(c,s,'revoked' if s['revoked'] else 'expired' if s['expires']<=time.time() else 'expiring')
        return previous_cleanup()
    app.cleanup=cleanup

    @app.get('/api/admin/statistics')
    @protected(admin=True)
    def statistics():
        try:days=int(request.args.get('days','30'))
        except ValueError:return fail('invalid_input')
        if days not in (7,30,90):return fail('invalid_input')
        today=int(time.time())//86400*86400
        since=today-(days-1)*86400
        with db() as c:
            daily={r['day']:r['count'] for r in c.execute("SELECT (created/86400)*86400 day,count(*) count FROM audit WHERE action IN ('file.downloaded','share.archive_downloaded') AND created>=? GROUP BY day",(since,))}
            history=[dict(day=day,downloads=daily.get(day,0)) for day in range(since,today+1,86400)]
            counts=dict(c.execute('SELECT sum(revoked=0 AND expires>?) active,sum(revoked=0 AND expires<=?) expired,sum(revoked=1) revoked,sum(password IS NOT NULL) protected FROM shares',(time.time(),time.time())).fetchone())
            top=[dict(r) for r in c.execute('SELECT title,downloads FROM shares ORDER BY downloads DESC LIMIT 10')]
            users=[dict(r) for r in c.execute('SELECT u.email,count(s.id) shares FROM users u LEFT JOIN shares s ON s.owner=u.id AND s.created>=? GROUP BY u.id ORDER BY shares DESC LIMIT 10',(since,))]
        return jsonify(history=history,counts={k:v or 0 for k,v in counts.items()},top_shares=top,top_users=users)
