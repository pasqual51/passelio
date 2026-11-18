"""Consistent full backups and offline restore into a new data directory.

python backup.py create --data /data --output /backup/passelio.zip
python backup.py verify --archive /backup/passelio.zip
python backup.py restore --archive /backup/passelio.zip --target /new-data
"""
from contextlib import closing
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import zipfile

FORMAT=1
SAFE=re.compile(r'^(passelio\.sqlite|smtp-password|account-signing-key|files/[a-f0-9]{48}|branding/[a-f0-9]{48}\.png)$')


def create(data,output):
    data,output=Path(data).resolve(),Path(output).absolute()
    if output.exists():raise ValueError('Output already exists')
    if not (data/'passelio.sqlite').is_file():raise ValueError('Database missing')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.backup-',dir=output.parent) as folder:
        folder=Path(folder);snapshot=folder/'passelio.sqlite'
        lock=sqlite3.connect(data/'passelio.sqlite',timeout=30)
        try:
            lock.row_factory=sqlite3.Row
            lock.execute('BEGIN IMMEDIATE')
            # A separate reader can back up WAL while writers/cleanup remain excluded.
            reader=sqlite3.connect(data/'passelio.sqlite')
            target=sqlite3.connect(snapshot)
            try:
                reader.backup(target)
                target.execute('PRAGMA journal_mode=DELETE')
                target.execute('DELETE FROM sessions');target.execute('DELETE FROM tickets')
                target.execute('DELETE FROM account_actions');target.execute('DELETE FROM uploads')
                target.execute('DELETE FROM files WHERE ready=0')
                target.commit()
            finally:target.close();reader.close()
            paths=[('passelio.sqlite',snapshot)]
            paths += [('files/'+r['id'],data/'files'/r['id']) for r in lock.execute('SELECT id FROM files WHERE ready=1')]
            paths += [('branding/'+r['id']+'.png',data/'branding'/(r['id']+'.png')) for r in lock.execute('SELECT id FROM branding_assets')]
            paths += [(name,data/name) for name in ('smtp-password','account-signing-key') if (data/name).is_file()]
            if any(not SAFE.fullmatch(name) or path.is_symlink() or not path.is_file() for name,path in paths):raise ValueError('Unsafe or missing source file')
            required=sum(path.stat().st_size for _,path in paths)
            if shutil.disk_usage(output.parent).free<required+64*1024**2:raise ValueError('Not enough backup disk space')
            archive=folder/'backup.zip';manifest={}
            with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as z:
                for name,path in paths:
                    digest=hashlib.sha256();size=0
                    with path.open('rb') as src,z.open(name,'w',force_zip64=True) as dst:
                        while chunk:=src.read(1024**2):dst.write(chunk);digest.update(chunk);size+=len(chunk)
                    manifest[name]={'size':size,'sha256':digest.hexdigest()}
                z.writestr('manifest.json',json.dumps({'format':FORMAT,'files':manifest}))
            os.chmod(archive,0o600)
            # Exclusive creation prevents overwriting an unrelated backup.
            with os.fdopen(os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as dest,archive.open('rb') as src:shutil.copyfileobj(src,dest)
            os.chmod(output,0o600)
        finally:lock.rollback();lock.close()
    return output


def verify(archive,max_bytes=100*1024**3):
    with zipfile.ZipFile(archive) as z:
        infos=z.infolist()
        if len(infos)>100000 or len({i.filename for i in infos})!=len(infos):raise ValueError('Duplicate or excessive archive entries')
        if 'manifest.json' not in z.namelist() or z.getinfo('manifest.json').file_size>16*1024**2:raise ValueError('Manifest missing or too large')
        manifest=json.loads(z.read('manifest.json'))
        if manifest.get('format')!=FORMAT or not isinstance(manifest.get('files'),dict):raise ValueError('Unsupported backup format')
        files=manifest['files']
        if set(z.namelist())!=set(files)|{'manifest.json'} or 'passelio.sqlite' not in files:raise ValueError('Invalid archive inventory')
        if sum(i.file_size for i in infos)>max_bytes:raise ValueError('Archive exceeds restore limit')
        for name,entry in files.items():
            if not SAFE.fullmatch(name) or not isinstance(entry,dict) or entry.get('size')!=z.getinfo(name).file_size:raise ValueError('Invalid archive entry')
            digest=hashlib.sha256();size=0
            with z.open(name) as src:
                while chunk:=src.read(1024**2):
                    size+=len(chunk)
                    if size>entry['size']:raise ValueError('Archive size mismatch')
                    digest.update(chunk)
            if digest.hexdigest()!=entry.get('sha256'):raise ValueError('Backup checksum mismatch')
    return files


def restore(archive,target,max_bytes=100*1024**3):
    target=Path(target).absolute()
    if target.exists():raise ValueError('Restore requires a new, nonexistent target directory')
    files=verify(archive,max_bytes)
    if not target.parent.is_dir():raise ValueError('Target parent directory missing')
    if shutil.disk_usage(target.parent).free<sum(v['size'] for v in files.values())+64*1024**2:raise ValueError('Not enough restore disk space')
    with tempfile.TemporaryDirectory(prefix='.restore-',dir=target.parent) as folder:
        staging=Path(folder)/'data';staging.mkdir(mode=0o700)
        with zipfile.ZipFile(archive) as z:
            for name in files:
                path=staging/name;path.parent.mkdir(parents=True,exist_ok=True)
                with path.open('xb') as dst,z.open(name) as src:shutil.copyfileobj(src,dst)
                os.chmod(path,0o600)
        with closing(sqlite3.connect(staging/'passelio.sqlite')) as c:
            if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Database integrity failure')
            if c.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN ('users','files','shares')").fetchone()[0]!=3:raise ValueError('Database schema missing')
        (staging/'files').mkdir(exist_ok=True);(staging/'branding').mkdir(exist_ok=True)
        staging.rename(target)
    return target


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    sub=commands.add_parser('create');sub.add_argument('--data',required=True);sub.add_argument('--output',required=True)
    for command in ('verify','restore'):
        sub=commands.add_parser(command);sub.add_argument('--archive',required=True)
        if command=='restore':sub.add_argument('--target',required=True)
    args=parser.parse_args()
    try:
        if args.command=='create':create(args.data,args.output)
        elif args.command=='verify':verify(args.archive)
        else:restore(args.archive,args.target)
    except (ValueError,OSError,zipfile.BadZipFile,sqlite3.Error):
        parser.exit(1,'Backup operation failed. Check paths, space, format and integrity.\n')
    print('Backup operation completed successfully.')
