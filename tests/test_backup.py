import zipfile
from unittest.mock import patch
import pytest
from backup import create,verify,restore
from test_app import app,login,share,upload
from app import create_app


def test_full_backup_restore_files_settings_and_session_invalidation(app,tmp_path):
    c,h=login(app);sid=share(c,h);fid=upload(c,h,sid).json['id']
    archive=tmp_path/'backup.zip'
    create(app.config['DATA_DIR'],archive)
    inventory=verify(archive)
    assert 'files/'+fid in inventory
    target=tmp_path/'restored'
    restore(archive,target)
    rebuilt=create_app({**app.config,'DATA_DIR':str(target)})
    with rebuilt.db() as db:assert db.execute('SELECT count(*) FROM sessions').fetchone()[0]==0
    result=rebuilt.test_client().get(f'/api/public/{sid}/files/{fid}')
    assert result.data==b'hello world';result.close()
    with pytest.raises(ValueError):restore(archive,target)
    with pytest.raises(ValueError):create(app.config['DATA_DIR'],archive)


def test_restore_rejects_unlisted_paths_and_modified_bytes(app,tmp_path):
    archive=tmp_path/'backup.zip';create(app.config['DATA_DIR'],archive)
    with zipfile.ZipFile(archive,'a') as z:z.writestr('../escape','bad')
    with pytest.raises(ValueError):verify(archive)
    assert not (tmp_path/'escape').exists()


def test_backup_releases_writer_lock_and_survives_concurrent_cleanup(app,tmp_path):
    c,h=login(app);sid=share(c,h);fid=upload(c,h,sid).json['id']
    real_zip=zipfile.ZipFile
    def clean_then_stream(*args,**kwargs):
        assert c.delete('/api/shares/'+sid,headers=h).status_code==200
        assert app.cleanup()==1
        return real_zip(*args,**kwargs)
    archive=tmp_path/'concurrent.zip'
    with patch('backup.zipfile.ZipFile',side_effect=clean_then_stream):
        create(app.config['DATA_DIR'],archive)
    assert 'files/'+fid in verify(archive)
    with zipfile.ZipFile(archive) as z:assert z.read('files/'+fid)==b'hello world'
