from pathlib import Path
from unittest.mock import patch
from test_app import app,login,share,upload
from backup import restore
from app import create_app


def test_queued_backup_retention_download_and_safe_restored_schedule(app,tmp_path):
    c,h=login(app);s=share(c,h);upload(c,h,s)
    assert app.run_backup_cycle() is False
    assert app.test_client().get('/api/admin/backups').status_code==401
    assert c.post('/api/admin/backups').status_code==403
    assert c.put('/api/admin/backups',headers=h,json={'enabled':True,'interval_hours':24,'retention':1}).status_code==200
    assert app.run_backup_cycle() is False
    assert c.post('/api/admin/backups',headers=h).status_code==202
    assert app.run_backup_cycle() is True
    data=c.get('/api/admin/backups').json
    assert data['settings']['last_success'] and not data['settings']['running']
    first=data['archives'][0]['name']
    response=c.get('/api/admin/backups/'+first)
    assert response.status_code==200 and response.data[:2]==b'PK';response.close()
    assert c.post('/api/admin/backups',headers=h).status_code==202
    assert app.run_backup_cycle() is True
    second=c.get('/api/admin/backups').json['archives']
    assert len(second)==1 and second[0]['name']!=first
    assert c.get('/api/admin/backups/'+first).status_code==404
    assert len(list((Path(app.config['DATA_DIR'])/'backups').glob('*.zip')))==1
    target=tmp_path/'restored'
    restore(Path(app.config['DATA_DIR'])/'backups'/second[0]['name'],target)
    reopened=create_app({**app.config,'DATA_DIR':str(target)})
    with reopened.db() as db:
        state=db.execute('SELECT * FROM backup_schedule').fetchone()
        assert not state['enabled'] and not state['lease_until']
        assert db.execute('SELECT count(*) FROM backup_archives').fetchone()[0]==0


def test_backup_failure_keeps_last_good_archive_and_hides_error_details(app):
    c,h=login(app)
    assert c.post('/api/admin/backups',headers=h).status_code==202
    assert app.run_backup_cycle()
    before=c.get('/api/admin/backups').json['archives']
    c.post('/api/admin/backups',headers=h)
    with patch('backup_manager.create',side_effect=ValueError('private server path and credentials')):
        assert not app.run_backup_cycle()
    state=c.get('/api/admin/backups').json
    assert state['archives']==before and state['settings']['last_error']=='backup_failed'
    assert 'credentials' not in str(state)
    assert c.put('/api/admin/backups',headers=h,json={'enabled':True,'interval_hours':1,'retention':100}).status_code==400


def test_backup_lease_prevents_duplicate_workers(app):
    c,h=login(app);c.post('/api/admin/backups',headers=h)
    import time
    with app.db(True) as db:db.execute('UPDATE backup_schedule SET lease_until=?',(int(time.time())+1000,))
    assert not app.run_backup_cycle()
