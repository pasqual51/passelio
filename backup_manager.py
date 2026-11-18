"""Opt-in retained full backups, claimed atomically and produced by the worker."""
import os
from pathlib import Path
import re
import secrets
import time

from flask import g, jsonify, request, send_file
from backup import create, verify

NAME=re.compile(r'^passelio-[0-9]{10}-[a-f0-9]{12}\.zip$')


def init_backup_manager(app,db,root,protected,fail,audit,rate_limit):
    destination=Path(app.config.get('BACKUP_DIR') or os.getenv('BACKUP_DIR') or Path(root)/'backups').resolve()
    destination.mkdir(mode=0o700,parents=True,exist_ok=True)
    with db() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS backup_schedule(id INTEGER PRIMARY KEY CHECK(id=1),
          enabled INTEGER NOT NULL DEFAULT 0,interval_hours INTEGER NOT NULL DEFAULT 24,
          retention INTEGER NOT NULL DEFAULT 7,next_due INTEGER NOT NULL DEFAULT 0,
          requested INTEGER NOT NULL DEFAULT 0,lease_until INTEGER NOT NULL DEFAULT 0,
          last_success INTEGER,last_error TEXT);
          INSERT OR IGNORE INTO backup_schedule(id) VALUES(1);
          CREATE TABLE IF NOT EXISTS backup_archives(name TEXT PRIMARY KEY,created INTEGER NOT NULL,size INTEGER NOT NULL);
        ''')

    @app.get('/api/admin/backups')
    @protected(admin=True)
    def backup_status():
        with db() as c:
            settings=dict(c.execute('SELECT * FROM backup_schedule WHERE id=1').fetchone())
            archives=[dict(r) for r in c.execute('SELECT * FROM backup_archives ORDER BY created DESC,rowid DESC')]
        settings.pop('id');settings['enabled']=bool(settings['enabled'])
        settings['running']=settings.pop('lease_until')>time.time()
        return jsonify(settings=settings,archives=archives)

    @app.put('/api/admin/backups')
    @protected(admin=True)
    def backup_configure():
        b=request.get_json(silent=True) or {}
        if set(b)!={'enabled','interval_hours','retention'} or type(b['enabled']) is not bool or type(b['interval_hours']) is not int or b['interval_hours'] not in (24,168) or type(b['retention']) is not int or not 1<=b['retention']<=14:return fail('invalid_input')
        with db(True) as c:
            c.execute('UPDATE backup_schedule SET enabled=?,interval_hours=?,retention=?,next_due=? WHERE id=1',
                      (int(b['enabled']),b['interval_hours'],b['retention'],int(time.time())+b['interval_hours']*3600))
            audit(c,'backup.configured')
        return jsonify(ok=True)

    @app.post('/api/admin/backups')
    @protected(admin=True)
    def backup_request():
        if not rate_limit('full-backup:'+str(g.user['id']),3):return fail('rate_limited',429)
        with db(True) as c:
            c.execute('UPDATE backup_schedule SET requested=1 WHERE id=1')
            audit(c,'backup.requested')
        return jsonify(ok=True),202

    @app.get('/api/admin/backups/<name>')
    @protected(admin=True)
    def backup_download(name):
        if not NAME.fullmatch(name):return fail('not_found',404)
        with db() as c:
            if not c.execute('SELECT 1 FROM backup_archives WHERE name=?',(name,)).fetchone():return fail('not_found',404)
        path=destination/name
        if not path.is_file() or path.is_symlink():return fail('not_found',404)
        return send_file(path,as_attachment=True,download_name=name,mimetype='application/zip',conditional=False)

    def run_cycle():
        now=int(time.time())
        with db(True) as c:
            settings=c.execute('SELECT * FROM backup_schedule WHERE id=1').fetchone()
            if settings['lease_until']>now or (not settings['requested'] and (not settings['enabled'] or settings['next_due']>now)):return False
            c.execute('UPDATE backup_schedule SET requested=0,lease_until=?,next_due=?,last_error=NULL WHERE id=1',
                      (now+86400,now+settings['interval_hours']*3600))
        name='passelio-'+str(now)+'-'+secrets.token_hex(6)+'.zip';path=destination/name
        try:
            create(root,path)
            verify(path)
            size=path.stat().st_size
        except Exception:
            path.unlink(missing_ok=True)
            with db(True) as c:
                c.execute("UPDATE backup_schedule SET lease_until=0,last_error='backup_failed',next_due=? WHERE id=1",(int(time.time())+3600,))
                audit(c,'backup.failed')
            return False
        # Register the verified archive before pruning; pruning failures must never
        # remove the newly completed backup or roll back its successful status.
        with db(True) as c:
            c.execute('INSERT INTO backup_archives VALUES(?,?,?)',(name,now,size))
            c.execute('UPDATE backup_schedule SET lease_until=0,last_success=?,last_error=NULL WHERE id=1',(int(time.time()),))
            audit(c,'backup.completed',name)
        with db(True) as c:
            retention=c.execute('SELECT retention FROM backup_schedule WHERE id=1').fetchone()[0]
            old=c.execute('SELECT name FROM backup_archives ORDER BY created DESC,rowid DESC LIMIT -1 OFFSET ?',(retention,)).fetchall()
            for row in old:
                if NAME.fullmatch(row['name']):
                    try:(destination/row['name']).unlink(missing_ok=True)
                    except OSError:continue
                    c.execute('DELETE FROM backup_archives WHERE name=?',(row['name'],))
        return True
    app.run_backup_cycle=run_cycle
