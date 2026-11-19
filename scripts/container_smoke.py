"""Run inside the candidate image with no network and a read-only root filesystem."""
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import ssl
import sqlite3
import pwd
import subprocess
import sys
import tempfile

sys.path.insert(0,'/app')
from app import create_app
from backup import create,verify,restore
from PIL import Image

assert os.getuid()==10001,'Container must run without root privileges'
assert pwd.getpwnam('passelio').pw_uid==10001
assert importlib.util.find_spec('pip') is None,'Package installer must not remain in the runtime image'
assert importlib.util.find_spec('ensurepip') is None,'Bundled installer must not remain in the runtime image'
zlib_package=subprocess.check_output(['dpkg-query','-W','-f=${Version}','zlib1g'],text=True).strip()
subprocess.run(['dpkg','--compare-versions',zlib_package,'ge','1:1.3.dfsg+really1.3.1-1+deb13u1'],check=True)
removed_packages=['apt','libapt-pkg7.0','mount','login','libncursesw6','adduser','passwd']
for name in removed_packages:
    result=subprocess.run(['dpkg-query','-W','-f=${db:Status-Status}',name],capture_output=True,text=True)
    assert result.stdout.strip()!='installed',name+' remains installed'
assert not subprocess.check_output(['dpkg','--audit'],text=True).strip()
assert ssl.create_default_context().cert_store_stats()['x509_ca']>0
for module in ['ctypes','_cffi_backend','bz2','lzma','readline','dbm.gnu','uuid']:__import__(module)
archive_tar=subprocess.run(['perl','-MArchive::Tar','-e','exit 0'],capture_output=True,text=True)
assert archive_tar.returncode!=0 and "Can't locate Archive/Tar.pm" in archive_tar.stderr
tooling={name:bool(shutil.which(name)) for name in ['apt-get','mount','umount','login','useradd','infocmp','nsenter','setfacl','systemd-homed']}
assert not any(tooling[name] for name in ['apt-get','mount','umount','login','useradd','systemd-homed'])
sqlite_options=[r[0] for r in sqlite3.connect(':memory:').execute('PRAGMA compile_options')]
with tempfile.TemporaryDirectory(prefix='passelio-smoke-') as directory:
    root=Path(directory);password=secrets.token_urlsafe(32);(root/'password').write_text(password)
    app=create_app(dict(TESTING=True,DATA_DIR=str(root/'data'),BASE_URL='http://localhost',ADMIN_EMAIL='smoke@example.invalid',ADMIN_PASSWORD_FILE=str(root/'password'),SECURE_COOKIES=False))
    c=app.test_client()
    assert c.get('/api/health').status_code==200
    assert c.post('/api/login',json={'email':'smoke@example.invalid','password':password}).status_code==200
    headers={'X-CSRF-Token':c.get('/api/me').json['csrf']}
    response=c.post('/api/shares',headers=headers,json={'title':'Container smoke check'})
    assert response.status_code==201;sid=response.json['id']
    data=b'Passelio isolated image smoke check'
    response=c.post('/api/shares/'+sid+'/files?name=sample.txt',headers=headers,data=data,content_type='application/octet-stream')
    assert response.status_code==201;fid=response.json['id']
    response=c.get('/api/public/'+sid+'/files/'+fid)
    assert response.status_code==200 and hashlib.sha256(response.data).digest()==hashlib.sha256(data).digest()
    response.close()
    archive=root/'full.zip';create(root/'data',archive,storage=app.storage);verify(archive);restore(archive,root/'restored')
    assert (root/'restored/files'/fid).read_bytes()==data
    Image.new('RGB',(32,32),'teal').save(root/'test.png')
    with Image.open(root/'test.png') as image:assert image.size==(32,32)
    with app.db() as connection:assert not connection.execute("SELECT 1 FROM sqlite_master WHERE sql LIKE 'CREATE VIRTUAL TABLE%'").fetchone()
print(json.dumps({'uid':os.getuid(),'pip':'absent','ensurepip':'absent','zlib_debian_package':zlib_package,'removed_packages':removed_packages,'dpkg_audit':'clean','tooling':tooling,'perl_Archive_Tar':'not_installed','sqlite_version':sqlite3.sqlite_version,'sqlite_compile_options':sqlite_options,'health_login_upload_download':'passed','full_backup_restore':'passed','pillow_png':'passed','native_modules_tls_ca':'passed','network':'disabled','root_filesystem':'read_only'}))
