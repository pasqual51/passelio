"""Quota-reserved, restartable uploads and validated relative folder paths."""
import json
import hashlib
import os
import secrets
import shutil
import time
from pathlib import PurePosixPath

from flask import g, jsonify, request


def valid_name(name):
    return (isinstance(name, str) and 0 < len(name) <= 240 and '\\' not in name
            and not name.startswith('/') and ':' not in name
            and all(ord(c) >= 32 for c in name)
            and all(p not in ('', '.', '..') for p in name.split('/'))
            and len(PurePosixPath(name).parts) <= 20)


def init_transfers(app, db, root, blobs, protected, fail, audit, limits):
    with db() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS uploads(
          id TEXT PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
          owner INTEGER NOT NULL REFERENCES users(id), offset INTEGER NOT NULL DEFAULT 0,
          expires INTEGER NOT NULL);''')

    with db() as c:
        if 'chunks' not in [r['name'] for r in c.execute('PRAGMA table_info(uploads)')]:
            c.execute("ALTER TABLE uploads ADD COLUMN chunks TEXT NOT NULL DEFAULT '[]'")

    @app.post('/api/shares/<sid>/uploads')
    @protected()
    def begin(sid):
        body = request.get_json(silent=True) or {}
        name, size = body.get('name'), body.get('size')
        if not valid_name(name) or type(size) is not int or size <= 0:
            return fail('invalid_input')
        fid = secrets.token_hex(24)
        with db(True) as c:
            share = c.execute('SELECT * FROM shares WHERE id=? AND owner=? AND revoked=0 AND expires>?',
                              (sid, g.user['id'], time.time())).fetchone()
            if not share:
                return fail('not_found', 404)
            used = c.execute('SELECT coalesce(sum(size),0) FROM files').fetchone()[0]
            share_used = c.execute('SELECT coalesce(sum(size),0) FROM files WHERE share_id=?', (sid,)).fetchone()[0]
            cap = limits(c)
            if used + size > cap['STORAGE_LIMIT'] or share_used + size > cap['SHARE_LIMIT'] or shutil.disk_usage(root).free < size + 64 * 1024**2:
                return fail('quota', 413)
            c.execute('INSERT INTO files(id,share_id,name,size,created) VALUES(?,?,?,?,?)',
                      (fid,sid,name,size,int(time.time())))
            c.execute('INSERT INTO uploads(id,owner,offset,expires) VALUES(?,?,0,?)',(fid,g.user['id'],int(time.time())+86400))
        return jsonify(id=fid,offset=0,chunk_size=8*1024**2),201

    def find(c, fid):
        return c.execute('SELECT f.*,u.offset,u.chunks FROM uploads u JOIN files f ON f.id=u.id JOIN shares s ON s.id=f.share_id '
                         'WHERE u.id=? AND u.owner=? AND u.expires>? AND s.revoked=0 AND s.expires>?',
                         (fid,g.user['id'],time.time(),time.time())).fetchone()

    @app.get('/api/uploads/<fid>')
    @protected()
    def status(fid):
        with db() as c:
            row=find(c,fid)
            if not row:return fail('not_found',404)
            return jsonify(id=fid,offset=row['offset'],size=row['size'],name=row['name'],chunks=json.loads(row['chunks']))

    @app.patch('/api/uploads/<fid>')
    @protected()
    def chunk(fid):
        size=request.content_length
        try:offset=int(request.headers.get('Upload-Offset',''))
        except ValueError:return fail('invalid_input')
        if not size or size>8*1024**2:return fail('too_large',413)
        data=request.get_data()
        if len(data)!=size:return fail('upload_failed')
        with db(True) as c:
            row=find(c,fid)
            if not row:return fail('not_found',404)
            if offset!=row['offset']:return jsonify(error='upload_offset',offset=row['offset']),409
            if offset+size>row['size']:return fail('too_large',413)
            chunks=json.loads(row['chunks'])
            if len(chunks)>=2048:return fail('too_large',413)
            path=blobs/fid
            with path.open('r+b' if path.exists() else 'w+b') as f:
                # Discard bytes written before a previous process crashed before committing.
                if f.seek(0,os.SEEK_END)<offset:return fail('upload_failed')
                f.truncate(offset);f.seek(offset);f.write(data);f.flush();os.fsync(f.fileno())
            chunks.append(dict(size=size,sha256=hashlib.sha256(data).hexdigest()))
            c.execute('UPDATE uploads SET offset=?,expires=?,chunks=? WHERE id=?',(offset+size,int(time.time())+86400,json.dumps(chunks),fid))
        return jsonify(offset=offset+size)

    @app.post('/api/uploads/<fid>/complete')
    @protected()
    def finish(fid):
        with db(True) as c:
            row=find(c,fid)
            if not row:return fail('not_found',404)
            if row['offset']!=row['size']:return fail('upload_failed')
            path=blobs/fid
            if not path.is_file() or path.stat().st_size!=row['size']:return fail('upload_failed')
            with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
            c.execute('UPDATE files SET ready=1,sha256=? WHERE id=?',(digest,fid))
            c.execute('DELETE FROM uploads WHERE id=?',(fid,))
            audit(c,'file.uploaded',fid)
        return jsonify(id=fid,sha256=digest)

    @app.delete('/api/uploads/<fid>')
    @protected()
    def cancel(fid):
        with db(True) as c:
            row=c.execute('SELECT id FROM uploads WHERE id=? AND owner=?',(fid,g.user['id'])).fetchone()
            if not row:return fail('not_found',404)
            (blobs/fid).unlink(missing_ok=True)
            c.execute('DELETE FROM files WHERE id=?',(fid,))
        return jsonify(ok=True)

    original_cleanup=app.cleanup
    def cleanup():
        count=original_cleanup()
        with db(True) as c:
            rows=c.execute('SELECT id FROM uploads WHERE expires<=?',(time.time(),)).fetchall()
            for row in rows:
                (blobs/row['id']).unlink(missing_ok=True)
                c.execute('DELETE FROM files WHERE id=?',(row['id'],))
        return count+len(rows)
    app.cleanup=cleanup
