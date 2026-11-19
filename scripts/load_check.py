"""Isolated concurrent upload/download smoke benchmark; never touches server data."""
import hashlib
import json
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import create_app


def main():
    with tempfile.TemporaryDirectory(prefix='passelio-load-') as folder:
        root=Path(folder);password='load-test-only-password-12345'
        (root/'password').write_text(password,encoding='utf-8')
        app=create_app(dict(TESTING=True,DATA_DIR=str(root/'data'),ADMIN_EMAIL='load@example.invalid',ADMIN_PASSWORD_FILE=str(root/'password'),SECURE_COOKIES=False,STORAGE_LIMIT=64*1024**2,SHARE_LIMIT=4*1024**2))
        clients=[]
        for _ in range(8):
            c=app.test_client();assert c.post('/api/login',json={'email':'load@example.invalid','password':password}).status_code==200
            clients.append((c,{'X-CSRF-Token':c.get('/api/me').json['csrf']}))
        payload=b'x'*1024**2;digest=hashlib.sha256(payload).hexdigest()
        def transfer(pair):
            c,h=pair;r=c.post('/api/shares',headers=h,json={'title':'Concurrent load check'});assert r.status_code==201
            sid=r.json['id'];r=c.post('/api/shares/'+sid+'/files?name=sample.bin',headers=h,data=payload,content_type='application/octet-stream');assert r.status_code==201
            assert r.json['sha256']==digest
            r=c.get('/api/public/'+sid+'/files/'+r.json['id']);assert r.status_code==200
            assert hashlib.sha256(r.data).hexdigest()==digest
        started=time.monotonic()
        with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(transfer,clients))
        print(json.dumps({'workers':8,'transfers':8,'bytes_each':len(payload),'seconds':round(time.monotonic()-started,3),'checksums':'passed','scope':'Flask test client; excludes HTTP proxy and remote storage'}))


if __name__=='__main__':main()
