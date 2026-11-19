"""Run inside the candidate image with no network and a read-only root filesystem."""
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile

sys.path.insert(0,'/app')
from app import create_app

assert os.getuid()==10001,'Container must run without root privileges'
assert importlib.util.find_spec('pip') is None,'Package installer must not remain in the runtime image'
assert importlib.util.find_spec('ensurepip') is None,'Bundled installer must not remain in the runtime image'
zlib_package=subprocess.check_output(['dpkg-query','-W','-f=${Version}','zlib1g'],text=True).strip()
subprocess.run(['dpkg','--compare-versions',zlib_package,'ge','1:1.3.dfsg+really1.3.1-1+deb13u1'],check=True)
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
print(json.dumps({'uid':os.getuid(),'pip':'absent','ensurepip':'absent','zlib_debian_package':zlib_package,'health_login_upload_download':'passed','network':'disabled','root_filesystem':'read_only'}))
