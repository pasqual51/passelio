import io
from pathlib import Path
import time
import zipfile
import pytest
from app import create_app
from blobstore import S3, SFTP
from backup import create,restore,verify
from test_app import app,login,share,upload


class Memory:
    def __init__(self,name):self.identity={'kind':name,'destination':'test'};self.objects={};self.fail=False
    def put(self,path,oid,size,digest):
        if self.fail:raise OSError('credentials and private path must not be returned')
        self.objects[oid]=Path(path).read_bytes()
    def open(self,oid,size):
        if self.fail:raise OSError('private error')
        assert len(self.objects[oid])==size
        return io.BytesIO(self.objects[oid])
    def delete(self,oid):
        if self.fail:raise OSError('unavailable')
        self.objects.pop(oid,None)
    def check(self):
        if self.fail:raise OSError('private error')
        return True


@pytest.mark.parametrize('backend',['s3','sftp'])
def test_remote_roundtrip_zip_cleanup_and_full_restore(app,tmp_path,backend):
    memory=Memory(backend)
    remote=create_app({**app.config,'STORAGE_CONFIG':{'default':backend},'STORAGE_ADAPTERS':{backend:memory}})
    c,h=login(remote);sid=share(c,h,password='share-password')
    fid=upload(c,h,sid).json['id']
    assert not (Path(app.config['DATA_DIR'])/'files'/fid).exists()
    guest=remote.test_client()
    assert guest.get(f'/api/public/{sid}/files/{fid}').status_code==403
    assert guest.post(f'/api/public/{sid}/unlock',json={'password':'share-password'}).status_code==200
    response=guest.get(f'/api/public/{sid}/files/{fid}');assert response.data==b'hello world';response.close()
    response=guest.get(f'/api/public/{sid}/archive')
    with zipfile.ZipFile(io.BytesIO(response.data)) as z:assert z.read('bonjour.txt')==b'hello world'
    response.close()
    archive=tmp_path/'full.zip';create(remote.config['DATA_DIR'],archive,storage=remote.storage)
    assert 'files/'+fid in verify(archive)
    target=tmp_path/'restored';restore(archive,target)
    local=create_app({**app.config,'DATA_DIR':str(target)})
    with local.db() as db:assert db.execute('SELECT storage FROM files').fetchone()[0]=='local'
    assert (target/'files'/fid).read_bytes()==b'hello world'
    oid=next(iter(memory.objects));original=memory.objects[oid]
    memory.objects[oid]=b'x'*len(original)
    with pytest.raises(ValueError):create(remote.config['DATA_DIR'],tmp_path/'corrupt.zip',storage=remote.storage)
    assert not (tmp_path/'corrupt.zip').exists()
    memory.objects[oid]=original
    assert c.delete('/api/shares/'+sid,headers=h).status_code==200
    assert remote.cleanup()==1
    assert memory.objects
    with remote.db(True) as db:db.execute('UPDATE storage_deletions SET created=?',(int(time.time())-120,))
    assert remote.storage.process_deletions()==1 and not memory.objects


def test_resumable_remote_failure_retries_and_destination_guard(app):
    memory=Memory('sftp')
    remote=create_app({**app.config,'STORAGE_CONFIG':{'default':'sftp'},'STORAGE_ADAPTERS':{'sftp':memory}})
    c,h=login(remote);sid=share(c,h)
    start=c.post(f'/api/shares/{sid}/uploads',headers=h,json={'name':'folder/file.txt','size':5}).json
    fid=start['id'];c.patch('/api/uploads/'+fid,headers={**h,'Upload-Offset':'0'},data=b'hello')
    memory.fail=True
    failed=c.post('/api/uploads/'+fid+'/complete',headers=h)
    assert failed.status_code==503 and failed.json=={'error':'storage_unavailable'}
    assert not remote.test_client().get('/api/public/'+sid).json['files']
    assert c.get('/api/uploads/'+fid).json['offset']==5
    memory.fail=False
    assert c.post('/api/uploads/'+fid+'/complete',headers=h).status_code==200
    other=Memory('sftp');other.identity['destination']='different'
    with pytest.raises(ValueError):create_app({**app.config,'STORAGE_CONFIG':{'default':'sftp'},'STORAGE_ADAPTERS':{'sftp':other}})
    with pytest.raises(ValueError):create_app(app.config)
    switched=create_app({**app.config,'STORAGE_CONFIG':{'default':'local'},'STORAGE_ADAPTERS':{'sftp':memory}})
    c2,h2=login(switched);sid2=share(c2,h2);assert upload(c2,h2,sid2).status_code==201
    with switched.db() as db:assert {r[0] for r in db.execute('SELECT storage FROM files')}=={'local','sftp'}


def test_remote_backup_pins_block_gc_and_failure_redaction(app,tmp_path):
    memory=Memory('s3');remote=create_app({**app.config,'STORAGE_CONFIG':{'default':'s3'},'STORAGE_ADAPTERS':{'s3':memory}})
    c,h=login(remote);sid=share(c,h);fid=upload(c,h,sid).json['id']
    original_open=memory.open
    def expire_during_backup(oid,size):
        c.delete('/api/shares/'+sid,headers=h);remote.cleanup()
        with remote.db(True) as db:db.execute('UPDATE storage_deletions SET created=?',(int(time.time())-120,))
        assert remote.storage.process_deletions()==0
        return original_open(oid,size)
    memory.open=expire_during_backup
    create(remote.config['DATA_DIR'],tmp_path/'pinned.zip',storage=remote.storage)
    with remote.db() as db:assert db.execute('SELECT count(*) FROM storage_pins').fetchone()[0]==0
    memory.fail=True
    assert c.post('/api/admin/storage-backends/s3/test',headers=h).json=={'error':'storage_unavailable'}
    state=c.get('/api/admin/storage-backends').json
    assert 'credentials' not in str(state) and 'destination' not in str(state)
    assert remote.test_client().get('/api/admin/storage-backends').status_code==401


def test_s3_sdk_upload_stream_delete_and_validation(tmp_path):
    from botocore.stub import Stubber
    from botocore.response import StreamingBody
    access=tmp_path/'access';access.write_text('test-access-key')
    secret=tmp_path/'secret';secret.write_text('test-secret-key')
    cfg={'bucket':'test-bucket','prefix':'passelio/','access_key_id_file':str(access),'secret_access_key_file':str(secret)}
    store=S3(cfg);stub=Stubber(store.client);oid='a'*48
    seen=[]
    store.client.meta.events.register('before-parameter-build.s3.PutObject',lambda params,**kwargs:seen.append(dict(params)))
    stub.add_response('put_object',{},expected_params=None)
    stub.add_response('head_object',{'ContentLength':5})
    stub.add_response('get_object',{'ContentLength':5,'Body':StreamingBody(io.BytesIO(b'hello'),5)})
    stub.add_response('delete_object',{})
    stub.add_response('head_bucket',{})
    path=tmp_path/'blob';path.write_bytes(b'hello')
    with stub:
        store.put(path,oid,5,'digest')
        with store.open(oid,5) as stream:assert stream.read()==b'hello'
        store.delete(oid);assert store.check()
    assert seen[0]['Key']=='passelio/'+oid and 'ACL' not in seen[0]
    assert seen[0]['Metadata']=={'sha256':'digest'}
    with pytest.raises(ValueError):S3({**cfg,'endpoint_url':'http://insecure.example'})
    with pytest.raises(ValueError):S3({**cfg,'prefix':'../unsafe'})
    with pytest.raises(ValueError):SFTP({'host':'example.invalid','username':'user','root':'/objects'})
