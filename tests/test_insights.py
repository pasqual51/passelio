from pathlib import Path
from test_app import app, login, share, upload
from test_mail import smtp_server, setup_mail


def test_templates_and_notification_idempotency(app,smtp_server):
    c,h=login(app);setup_mail(app,c,h,smtp_server)
    assert app.test_client().get('/api/admin/templates').status_code==401
    assert c.put('/api/admin/templates/reset/fr',headers=h,json={'subject':'Test','body':'No link'}).status_code==400
    assert c.put('/api/admin/templates/reset/fr',headers=h,json={'subject':'Test','body':'${unknown} ${url}'}).status_code==400
    assert c.put('/api/admin/templates/reset/fr',headers=h,json={'subject':'Test','body':'Lien : ${url}'}).status_code==200
    assert c.get('/api/admin/templates').json['templates']['reset']['fr']['body']=='Lien : ${url}'
    assert c.put('/api/admin/notifications',headers=h,json={'enabled':True}).status_code==200
    sid=share(c,h);fid=upload(c,h,sid).json['id']
    guest=app.test_client()
    for _ in range(2):
        r=guest.get(f'/api/public/{sid}/files/{fid}');assert r.status_code==200;r.close()
    assert app.process_mail()==1
    assert smtp_server.messages[0][0]==['admin@example.com']
    data=c.get('/api/admin/statistics?days=7').json
    assert sum(day['downloads'] for day in data['history'])==2
    assert len(data['history'])==7 and data['top_shares'][0]['downloads']==2
    assert c.get('/api/admin/statistics?days=100000').status_code==400


def test_frontend_is_paired_with_running_backend(app):
    # Regression: a newly edited script must not be served by an old app process.
    source=Path(app.static_folder)/'.test-version-pairing.js'
    assert app.test_client().get('/static/.test-version-pairing.js').status_code==404
    try:
        source.write_text('newBackendOnly();',encoding='utf-8')
        assert app.test_client().get('/static/.test-version-pairing.js').status_code==404
        assert app.test_client().get('/').status_code==200
    finally:
        source.unlink(missing_ok=True)
