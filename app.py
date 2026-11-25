"""Passelio private alpha. Local storage, explicit server-side sessions."""
import hashlib
import os
import secrets
import shutil
import sqlite3
import time
import json
import io
import tempfile
import mimetypes
import zipfile
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, g, jsonify, request, send_file, has_request_context
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash
from mailer import init_mail,validate_settings,address,addresses
from branding import init_branding
from accounts import init_accounts
from account_policy import init_account_policy
from identity import init_identity
from transfers import init_transfers, valid_name
from insights import init_insights
from requests_upload import init_upload_requests
from mfa import init_mfa
from backup_manager import init_backup_manager
from blobstore import init_storage, StorageUnavailable


def create_app(config=None):
    # Gunicorn workers and the queue worker may start against a fresh volume
    # together. Serialize the complete schema/bootstrap sequence, including all
    # extension migrations, using a separate SQLite connection across processes.
    root = Path((config or {}).get('DATA_DIR', os.getenv('DATA_DIR', './data'))).resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = sqlite3.connect(root / '.initialization.sqlite', timeout=120)
    try:
        lock.execute('BEGIN IMMEDIATE')
        return _create_app(config)
    finally:
        lock.rollback()
        lock.close()


def _create_app(config=None):
    app = Flask(__name__, static_folder="static")
    # Keep frontend files paired with the running backend until the next restart.
    # Development edits must not expose new API calls to an older process.
    static_root = Path(app.static_folder)
    frontend = {p.relative_to(static_root).as_posix(): p.read_bytes()
                for p in static_root.rglob('*') if p.is_file()}
    def bundled_static(filename):
        if filename not in frontend:
            return jsonify(error='not_found'), 404
        return send_file(io.BytesIO(frontend[filename]), mimetype=mimetypes.guess_type(filename)[0] or 'application/octet-stream')
    app.view_functions['static'] = bundled_static
    app.config.update(DATA_DIR=os.getenv("DATA_DIR", "./data"),
                      BASE_URL=os.getenv("BASE_URL", "http://localhost:8080"),
                      SECURE_COOKIES=os.getenv("SECURE_COOKIES", "true").lower() == "true",
                      STORAGE_LIMIT=int(os.getenv("STORAGE_LIMIT", str(20 * 1024**3))),
                      SHARE_LIMIT=int(os.getenv("SHARE_LIMIT", str(2 * 1024**3))),
                      ADMIN_EMAIL=os.getenv("ADMIN_EMAIL", ""),
                      ADMIN_PASSWORD_FILE=os.getenv("ADMIN_PASSWORD_FILE", ""))
    if config:
        app.config.update(config)
    base = urlsplit(app.config["BASE_URL"])
    if base.scheme not in ("http", "https") or not base.netloc or base.path not in ("", "/"):
        raise ValueError("BASE_URL must be an HTTP(S) origin without a path")
    app.config["MAX_CONTENT_LENGTH"] = app.config["SHARE_LIMIT"]
    root = Path(app.config["DATA_DIR"]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    blobs = root / "files"
    blobs.mkdir(exist_ok=True)

    @contextmanager
    def db(write=False):
        c = sqlite3.connect(root / "passelio.sqlite", timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                c.execute("BEGIN IMMEDIATE")
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    with db() as c:
        c.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL,
          password TEXT NOT NULL, admin INTEGER NOT NULL DEFAULT 0, language TEXT NOT NULL DEFAULT 'auto');
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
          csrf TEXT NOT NULL, expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS shares(id TEXT PRIMARY KEY, owner INTEGER NOT NULL REFERENCES users(id),
          title TEXT NOT NULL, created INTEGER NOT NULL, expires INTEGER NOT NULL, password TEXT,
          revoked INTEGER NOT NULL DEFAULT 0, downloads INTEGER NOT NULL DEFAULT 0, max_downloads INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS files(id TEXT PRIMARY KEY, share_id TEXT NOT NULL REFERENCES shares(id),
          name TEXT NOT NULL, size INTEGER NOT NULL, sha256 TEXT, ready INTEGER NOT NULL DEFAULT 0,
          created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS tickets(token TEXT PRIMARY KEY, share_id TEXT NOT NULL, expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts(bucket TEXT NOT NULL, created INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS attempts_bucket ON attempts(bucket,created);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, created INTEGER NOT NULL,
          user_id INTEGER, action TEXT NOT NULL, target TEXT);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS system_config(id INTEGER PRIMARY KEY CHECK(id=1),value TEXT NOT NULL);
        """)
    with db(True) as c:
        if 'active' not in [r['name'] for r in c.execute('PRAGMA table_info(users)')]:
            c.execute('ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1')
        if c.execute("SELECT count(*) FROM users").fetchone()[0] == 0:
            email = app.config["ADMIN_EMAIL"].strip().lower()
            password_file = app.config["ADMIN_PASSWORD_FILE"]
            if not email or not password_file:
                raise ValueError("First run requires ADMIN_EMAIL and ADMIN_PASSWORD_FILE")
            password = Path(password_file).read_text().rstrip("\r\n")
            if len(password) < 14:
                raise ValueError("Initial password must contain at least 14 characters")
            c.execute("INSERT INTO users(email,password,admin) VALUES(?,?,1)",
                      (email, generate_password_hash(password)))

    def fail(code, status=400):
        return jsonify(error=code), status

    def system_settings(connection=None):
        if connection is None:
            with db() as c:return system_settings(c)
        defaults=dict(application_name='Passelio',application_url=app.config['BASE_URL'].rstrip('/'),
                      login_message='',default_language='en',default_days=7,max_days=30,
                      default_downloads=0,require_share_password=False,session_hours=12)
        row=connection.execute('SELECT value FROM system_config WHERE id=1').fetchone()
        if row:defaults.update(json.loads(row['value']))
        return defaults

    app.system_settings=system_settings

    def audit(c, action, target=None):
        c.execute("INSERT INTO audit(created,user_id,action,target) VALUES(?,?,?,?)",
                  (int(time.time()), g.get("user", {}).get("id") if has_request_context() else None, action, target))

    def rate_limit(bucket, limit):
        now = int(time.time())
        with db(True) as c:
            c.execute("DELETE FROM attempts WHERE created<?", (now - 900,))
            count = c.execute("SELECT count(*) FROM attempts WHERE bucket=?", (bucket,)).fetchone()[0]
            if count >= limit:
                return False
            c.execute("INSERT INTO attempts VALUES(?,?)", (bucket, now))
        return True

    def protected(admin=False):
        def decorate(fn):
            @wraps(fn)
            def wrapper(*args, **kwargs):
                token = request.cookies.get("passelio_session", "")
                with db() as c:
                    row = c.execute("SELECT users.*,sessions.csrf FROM sessions JOIN users ON users.id=sessions.user_id "
                                    "WHERE token=? AND expires>?", (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
                if not row or not row['active']:
                    return fail("unauthorized", 401)
                g.user = dict(row)
                if admin and not row["admin"]:
                    return fail("forbidden", 403)
                if request.method not in ("GET", "HEAD", "OPTIONS"):
                    if not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), row["csrf"]):
                        return fail("csrf", 403)
                return fn(*args, **kwargs)
            return wrapper
        return decorate

    def available(c, share):
        return share and not share["revoked"] and share["expires"] > time.time()

    def unlocked(c, share):
        if not share["password"]:
            return True
        ticket = hashlib.sha256(request.cookies.get("passelio_share", "").encode()).hexdigest()
        return bool(c.execute("SELECT 1 FROM tickets WHERE token=? AND share_id=? AND expires>?",
                              (ticket, share["id"], time.time())).fetchone())

    def cleanup():
        # Explicit CLI task: a single transaction prevents quota/cleanup races.
        with db(True) as c:
            rows = c.execute("SELECT files.* FROM files JOIN shares ON shares.id=files.share_id "
                             "WHERE shares.revoked=1 OR shares.expires<=?", (time.time(),)).fetchall()
            for row in rows:
                app.storage.queue_delete(c,row)
                (blobs / row["id"]).unlink(missing_ok=True)
                c.execute("DELETE FROM files WHERE id=?", (row["id"],))
            c.execute("DELETE FROM sessions WHERE expires<=?", (time.time(),))
            c.execute("DELETE FROM tickets WHERE expires<=?", (time.time(),))
        return len(rows)

    app.cleanup = cleanup
    app.db = db
    app.config.setdefault('ALLOW_INSECURE_SMTP',os.getenv('ALLOW_INSECURE_SMTP','false').lower()=='true')
    init_mail(app,db,root)

    @app.cli.command("cleanup")
    def cleanup_command():
        print(f"Removed {app.cleanup()} expired/revoked files")

    @app.before_request
    def check_origin():
        if request.method=='POST' and request.path.startswith('/api/admin/branding/assets/'):
            request.max_content_length=5*1024**2
        elif request.method=='PATCH' and (request.path.startswith('/api/uploads/') or request.path.startswith('/api/requests/')):
            request.max_content_length=8*1024**2
        elif not (request.method == 'POST' and request.path.startswith('/api/shares/') and request.path.endswith('/files')):
            request.max_content_length = 65536 if request.path=='/api/admin/mail/settings' or request.path.startswith(('/api/admin/storage-configuration/','/api/admin/templates/')) else 16384
        else:
            request.max_content_length = current_limits()['SHARE_LIMIT']
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("Origin")
            if origin and origin not in (app.config["BASE_URL"].rstrip("/"),system_settings()['application_url']):
                return fail("csrf", 403)
            if request.is_json and not isinstance(request.get_json(silent=True),dict):
                return fail("invalid_input")

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(HTTPException)
    def http_error(e):
        return fail("too_large" if e.code == 413 else "request_error", e.code)

    @app.get("/")
    @app.get("/admin")
    @app.get("/s/<share_id>")
    @app.get("/r/<share_id>")
    def index(share_id=None):
        return bundled_static("index.html")

    @app.get("/api/health")
    def health():
        return jsonify(status="ok", version="0.1.0-alpha.16")

    @app.get('/api/config')
    def public_config():
        config=system_settings()
        return jsonify({k:v for k,v in config.items() if k!='session_hours'})

    @app.post("/api/login")
    def login():
        body = request.get_json(silent=True) or {}
        if not rate_limit("login:" + (request.remote_addr or "unknown"), 15):
            return fail("rate_limited", 429)
        email, password = body.get("email", ""), body.get("password", "")
        if not isinstance(email, str) or not isinstance(password, str) or len(password) > 1024:
            return fail("invalid_credentials", 401)
        with db() as c:
            user = c.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
        # Always perform a password hash calculation, including unknown accounts.
        stored = user["password"] if user else generate_password_hash("unavailable-account")
        if not check_password_hash(stored, password) or not user or not user['active'] or not user['email_verified']:
            return fail("invalid_credentials", 401)
        if not rate_limit('login-account:'+str(user['id']),15):return fail('rate_limited',429)
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        duration=system_settings()['session_hours']*3600
        with db(True) as c:
            current=c.execute('SELECT password,active FROM users WHERE id=?',(user['id'],)).fetchone()
            if not current or not current['active'] or current['password']!=user['password']:return fail('invalid_credentials',401)
            mfa_error=app.verify_mfa_login(user['id'],body.get('code'),c)
            if mfa_error:return fail(mfa_error,401)
            c.execute("INSERT INTO sessions VALUES(?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), user["id"], csrf, int(time.time()) + duration))
        response = jsonify(ok=True)
        response.set_cookie("passelio_session", token, max_age=duration, httponly=True, secure=app.config["SECURE_COOKIES"], samesite="Strict")
        return response

    @app.get("/api/me")
    @protected()
    def me():
        return jsonify({k: g.user[k] for k in ("id", "email", "admin", "language", "csrf")})

    @app.post("/api/logout")
    @protected()
    def logout():
        with db(True) as c:
            c.execute("DELETE FROM sessions WHERE token=?", (hashlib.sha256(request.cookies.get("passelio_session", "").encode()).hexdigest(),))
        response = jsonify(ok=True)
        response.delete_cookie("passelio_session")
        return response

    @app.put("/api/me/language")
    @protected()
    def language():
        value = (request.get_json(silent=True) or {}).get("language")
        if value not in ("fr", "en"):
            return fail("invalid_input")
        with db(True) as c:
            c.execute("UPDATE users SET language=? WHERE id=?", (value, g.user["id"]))
        return jsonify(ok=True)

    @app.put("/api/me/password")
    @protected()
    def change_password():
        b=request.get_json(silent=True) or {}
        old,new=b.get('current_password',''),b.get('password','')
        if not isinstance(old,str) or not isinstance(new,str) or len(old)>1024 or not 14<=len(new)<=1024:
            return fail('invalid_input')
        if not rate_limit('password:'+str(g.user['id']),10):
            return fail('rate_limited',429)
        if not check_password_hash(g.user['password'],old):
            return fail('invalid_credentials',401)
        with db(True) as c:
            c.execute('UPDATE users SET password=? WHERE id=?',(generate_password_hash(new),g.user['id']))
            c.execute('DELETE FROM sessions WHERE user_id=?',(g.user['id'],))
            audit(c,'user.password_changed',str(g.user['id']))
        response=jsonify(ok=True)
        response.delete_cookie('passelio_session')
        return response

    @app.post("/api/users")
    @protected(admin=True)
    def add_user():
        b = request.get_json(silent=True) or {}
        email, password = b.get("email", ""), b.get("password", "")
        if not isinstance(email, str) or not isinstance(password, str) or "@" not in email or len(email)>254 or not 14 <= len(password) <= 1024:
            return fail("invalid_input")
        try:
            with db(True) as c:
                c.execute("INSERT INTO users(email,password) VALUES(?,?)", (email.strip().lower(), generate_password_hash(password)))
                audit(c, "user.created", email.strip().lower())
        except sqlite3.IntegrityError:
            return fail("already_exists", 409)
        return jsonify(ok=True), 201

    @app.get("/api/shares")
    @protected()
    def list_shares():
        with db() as c:
            shares = c.execute("SELECT id,title,created,expires,revoked,downloads,max_downloads FROM shares WHERE owner=? ORDER BY created DESC", (g.user["id"],)).fetchall()
            used = c.execute("SELECT coalesce(sum(size),0) FROM files").fetchone()[0]
        limits=current_limits()
        return jsonify(shares=[dict(s) for s in shares], used=used, storage_limit=limits['STORAGE_LIMIT'], share_limit=limits['SHARE_LIMIT'])

    @app.post("/api/shares")
    @protected()
    def create_share():
        b = request.get_json(silent=True) or {}
        config=system_settings()
        title, password = b.get("title", ""), b.get("password", "")
        try:
            days, limit = int(b.get("days", config['default_days'])), int(b.get("max_downloads", config['default_downloads']))
        except (ValueError, TypeError):
            return fail("invalid_input")
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 150 or not isinstance(password, str) or len(password)>1024 or not 1 <= days <= config['max_days'] or not 0 <= limit <= 100000:
            return fail("invalid_input")
        if config['require_share_password'] and len(password)<8:return fail('share_password_required')
        sid = secrets.token_urlsafe(24)
        with db(True) as c:
            count = c.execute("SELECT count(*) FROM shares WHERE owner=? AND expires>? AND revoked=0", (g.user["id"], time.time())).fetchone()[0]
            if count >= 100:
                return fail("share_count", 409)
            c.execute("INSERT INTO shares(id,owner,title,created,expires,password,max_downloads) VALUES(?,?,?,?,?,?,?)",
                      (sid,g.user["id"],title.strip(),int(time.time()),int(time.time())+days*86400,generate_password_hash(password) if password else None,limit))
            audit(c, "share.created", sid)
        return jsonify(id=sid, url=config['application_url']+"/s/"+sid), 201

    @app.post("/api/shares/<sid>/files")
    @protected()
    def upload(sid):
        size = request.content_length
        name = request.args.get("name", "")
        if size is None or size <= 0 or not valid_name(name):
            return fail("invalid_input")
        fid = secrets.token_hex(24)
        storage=app.storage;backend=storage.default
        with db(True) as c:
            storage.ensure_binding(c,backend)
            share = c.execute("SELECT * FROM shares WHERE id=? AND owner=?", (sid,g.user["id"])).fetchone()
            if not available(c, share):
                return fail("not_found", 404)
            share_size = c.execute("SELECT coalesce(sum(size),0) FROM files WHERE share_id=?", (sid,)).fetchone()[0]
            total = c.execute("SELECT coalesce(sum(size),0) FROM files").fetchone()[0]
            limits=current_limits(c)
            if not app.user_quota_allows(c,g.user['id'],size):return fail('user_quota',413)
            if share_size+size > limits['SHARE_LIMIT'] or total+size > limits['STORAGE_LIMIT'] or shutil.disk_usage(root).free < size+64*1024**2:
                return fail("quota", 413)
            c.execute("INSERT INTO files(id,share_id,name,size,created,storage) VALUES(?,?,?,?,?,?)", (fid,sid,name,size,int(time.time()),backend))
        stored=None
        try:
            written, digest = 0, hashlib.sha256()
            with (blobs/fid).open("xb") as f:
                while chunk := request.stream.read(1024*1024):
                    written += len(chunk)
                    if written > size:
                        raise ValueError("size mismatch")
                    f.write(chunk)
                    digest.update(chunk)
            if written != size:
                raise ValueError("size mismatch")
            with db(True) as c:stored=app.storage.allocate(c,fid)
            app.storage.put(stored,blobs/fid,digest.hexdigest())
            with db(True) as c:
                share = c.execute("SELECT * FROM shares WHERE id=?", (sid,)).fetchone()
                current=c.execute("SELECT object_id FROM files WHERE id=?",(fid,)).fetchone()
                if not available(c,share) or not current or current["object_id"]!=stored["object_id"]:
                    raise ValueError("share expired")
                c.execute("UPDATE files SET sha256=?,ready=1 WHERE id=?", (digest.hexdigest(),fid))
                audit(c,"file.uploaded",fid)
        except Exception as exc:
            (blobs/fid).unlink(missing_ok=True)
            with db(True) as c:
                if stored:app.storage.queue_delete(c,stored)
                c.execute("DELETE FROM files WHERE id=?", (fid,))
            return fail('storage_unavailable' if isinstance(exc,StorageUnavailable) else 'upload_failed',503 if isinstance(exc,StorageUnavailable) else 400)
        if stored['storage']!='local':
            try:(blobs/fid).unlink(missing_ok=True)
            except OSError:pass
        return jsonify(id=fid,sha256=digest.hexdigest()), 201

    @app.delete("/api/shares/<sid>")
    @protected()
    def revoke(sid):
        with db(True) as c:
            n=c.execute("UPDATE shares SET revoked=1 WHERE id=? AND owner=?",(sid,g.user["id"])).rowcount
            if not n:
                return fail("not_found",404)
            audit(c,"share.revoked",sid)
        return jsonify(ok=True)

    @app.get("/api/public/<sid>")
    def public_share(sid):
        with db() as c:
            s=c.execute("SELECT * FROM shares WHERE id=?",(sid,)).fetchone()
            if not available(c,s):
                return fail("not_found",404)
            locked=not unlocked(c,s)
            files=[] if locked else [dict(f) for f in c.execute("SELECT id,name,size,sha256 FROM files WHERE share_id=? AND ready=1",(sid,))]
            return jsonify(title=s["title"],expires=s["expires"],locked=locked,files=files)

    @app.post("/api/public/<sid>/unlock")
    def unlock(sid):
        if not rate_limit("unlock:"+(request.remote_addr or "unknown")+":"+sid,10):
            return fail("rate_limited",429)
        password=(request.get_json(silent=True) or {}).get("password","")
        if not isinstance(password,str) or len(password)>1024:
            return fail("invalid_input")
        with db(True) as c:
            s=c.execute("SELECT * FROM shares WHERE id=?",(sid,)).fetchone()
            if not available(c,s):
                return fail("not_found",404)
            if s["password"] and not check_password_hash(s["password"],password):
                return fail("invalid_credentials",401)
            ticket=secrets.token_urlsafe(32)
            c.execute("INSERT INTO tickets VALUES(?,?,?)",(hashlib.sha256(ticket.encode()).hexdigest(),sid,int(time.time())+3600))
        response=jsonify(ok=True)
        response.set_cookie("passelio_share",ticket,max_age=3600,secure=app.config["SECURE_COOKIES"],httponly=True,samesite="Strict",path="/api/public/"+sid)
        return response

    @app.route("/api/public/<sid>/files/<fid>",methods=["GET"])
    def download(sid,fid):
        # HEAD must not consume a download allowance.
        with db(True) as c:
            s=c.execute("SELECT * FROM shares WHERE id=?",(sid,)).fetchone()
            if not available(c,s):
                return fail("not_found",404)
            if not unlocked(c,s):
                return fail("locked",403)
            f=c.execute("SELECT * FROM files WHERE id=? AND share_id=? AND ready=1",(fid,sid)).fetchone()
            if not f:
                return fail("not_found",404)
            if s["max_downloads"] and s["downloads"]>=s["max_downloads"]:
                return fail("download_limit",410)
            if request.method != "HEAD":
                c.execute("UPDATE shares SET downloads=downloads+1 WHERE id=?",(sid,))
                audit(c,"file.downloaded",fid)
                app.schedule_notification(c,s,"download")
            storage=app.storage;storage.ensure_binding(c,f['storage'])
            stream=storage.open(f)
            try:
                response=send_file(stream,as_attachment=True,download_name=f["name"],mimetype="application/octet-stream",conditional=False)
                response.content_length=f['size'];response.call_on_close(stream.close)
                return response
            except Exception:stream.close();raise

    @app.get('/api/public/<sid>/archive')
    def archive(sid):
        if not rate_limit('archive:'+(request.remote_addr or 'unknown'),5):return fail('rate_limited',429)
        with db(True) as c:
            s=c.execute('SELECT * FROM shares WHERE id=?',(sid,)).fetchone()
            if not available(c,s):return fail('not_found',404)
            if not unlocked(c,s):return fail('locked',403)
            if s['max_downloads'] and s['downloads']>=s['max_downloads']:return fail('download_limit',410)
            rows=c.execute('SELECT * FROM files WHERE share_id=? AND ready=1',(sid,)).fetchall()
            if not rows:return fail('not_found',404)
            if shutil.disk_usage(root).free<sum(r['size'] for r in rows)+64*1024**2:return fail('quota',413)
            stream=tempfile.TemporaryFile(dir=root)
            try:
                seen=set()
                with zipfile.ZipFile(stream,'w',zipfile.ZIP_STORED,allowZip64=True) as z:
                    for row in rows:
                        name=row['name']
                        if not valid_name(name):raise ValueError('Invalid archive name')
                        if name in seen:name=row['id']+'/'+name
                        seen.add(name)
                        storage=app.storage;storage.ensure_binding(c,row['storage'])
                        with storage.open(row) as source,z.open(name,'w',force_zip64=True) as destination:
                            shutil.copyfileobj(source,destination,1024**2)
                stream.seek(0)
                if request.method!='HEAD':
                    c.execute('UPDATE shares SET downloads=downloads+1 WHERE id=?',(sid,))
                    audit(c,'share.archive_downloaded',sid)
                    app.schedule_notification(c,s,'download')
                response=send_file(stream,as_attachment=True,download_name='passelio-'+sid+'.zip',mimetype='application/zip',conditional=False)
                response.call_on_close(stream.close)
                return response
            except Exception:
                stream.close()
                raise

    def current_limits(connection=None):
        if connection is None:
            with db() as c:
                return current_limits(c)
        values={key:app.config[key] for key in ('STORAGE_LIMIT','SHARE_LIMIT')}
        values.update({r['key']:r['value'] for r in connection.execute('SELECT key,value FROM settings')})
        return values

    @app.get('/api/admin/overview')
    @protected(admin=True)
    def admin_overview():
        with db() as c:
            result=dict(users=c.execute('SELECT count(*) FROM users').fetchone()[0],
                        active_users=c.execute('SELECT count(*) FROM users WHERE active=1').fetchone()[0],
                        shares=c.execute('SELECT count(*) FROM shares WHERE revoked=0 AND expires>?',(time.time(),)).fetchone()[0],
                        files=c.execute('SELECT count(*) FROM files WHERE ready=1').fetchone()[0],
                        used=c.execute('SELECT coalesce(sum(size),0) FROM files').fetchone()[0],
                        cleanup_bytes=c.execute('SELECT coalesce(sum(size),0) FROM files JOIN shares ON shares.id=files.share_id WHERE revoked=1 OR expires<=?',(time.time(),)).fetchone()[0],
                        limits=current_limits(c),disk_free=shutil.disk_usage(root).free,version='0.1.0-alpha.16')
        return jsonify(result)

    @app.get('/api/admin/users')
    @protected(admin=True)
    def admin_users():
        q=request.args.get('q','')[:254].lower()
        with db() as c:
            rows=c.execute('SELECT u.id,u.email,u.admin,u.active,u.language,count(DISTINCT s.id) AS shares,coalesce(sum(f.size),0) AS used FROM users u LEFT JOIN shares s ON s.owner=u.id LEFT JOIN files f ON f.share_id=s.id WHERE instr(lower(u.email),?)>0 GROUP BY u.id ORDER BY u.email LIMIT 200',(q,)).fetchall()
        return jsonify(users=[dict(r) for r in rows])

    @app.patch('/api/admin/users/<int:uid>')
    @protected(admin=True)
    def admin_user_update(uid):
        b=request.get_json(silent=True) or {}
        if not b or any(k not in ('active','admin') or type(v) is not bool for k,v in b.items()):
            return fail('invalid_input')
        with db(True) as c:
            row=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
            if not row:return fail('not_found',404)
            if uid==g.user['id'] and (b.get('active') is False or b.get('admin') is False):
                return fail('self_admin',409)
            if row['admin'] and row['active'] and (b.get('active') is False or b.get('admin') is False):
                if c.execute('SELECT count(*) FROM users WHERE active=1 AND admin=1').fetchone()[0]<=1:
                    return fail('last_admin',409)
            active=int(b.get('active',bool(row['active'])));admin=int(b.get('admin',bool(row['admin'])))
            c.execute('UPDATE users SET active=?,admin=? WHERE id=?',(active,admin,uid))
            c.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
            audit(c,'user.updated',str(uid))
        return jsonify(ok=True)

    @app.get('/api/admin/shares')
    @protected(admin=True)
    def admin_shares():
        q=request.args.get('q','')[:254].lower();state=request.args.get('state','all')
        try:page=max(1,int(request.args.get('page','1')))
        except ValueError:return fail('invalid_input')
        if page>100000 or state not in ('all','active','expired','revoked'):return fail('invalid_input')
        predicates={'all':'1=1','active':'s.revoked=0 AND s.expires>?','expired':'s.revoked=0 AND s.expires<=?','revoked':'s.revoked=1'}
        args=[q,q]+([time.time()] if state in ('active','expired') else [])
        where='(instr(lower(s.title),?)>0 OR instr(lower(u.email),?)>0) AND '+predicates[state]
        with db() as c:
            total=c.execute('SELECT count(*) FROM shares s JOIN users u ON u.id=s.owner WHERE '+where,args).fetchone()[0]
            rows=c.execute('SELECT s.id,s.title,s.created,s.expires,s.revoked,s.downloads,s.max_downloads,u.email AS owner,count(f.id) AS files,coalesce(sum(f.size),0) AS size FROM shares s JOIN users u ON u.id=s.owner LEFT JOIN files f ON f.share_id=s.id WHERE '+where+' GROUP BY s.id ORDER BY s.created DESC,s.id LIMIT 200 OFFSET ?',args+[(page-1)*200]).fetchall()
        return jsonify(shares=[dict(r) for r in rows],page=page,pages=max(1,(total+199)//200),total=total)

    @app.delete('/api/admin/shares/<sid>')
    @protected(admin=True)
    def admin_revoke(sid):
        with db(True) as c:
            if not c.execute('UPDATE shares SET revoked=1 WHERE id=?',(sid,)).rowcount:
                return fail('not_found',404)
            audit(c,'admin.share_revoked',sid)
        return jsonify(ok=True)

    @app.get('/api/admin/audit')
    @protected(admin=True)
    def admin_audit():
        with db() as c:
            rows=c.execute('SELECT a.id,a.created,a.action,a.target,u.email AS actor FROM audit a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 200').fetchall()
        return jsonify(events=[dict(r) for r in rows])

    @app.put('/api/admin/settings')
    @protected(admin=True)
    def admin_settings():
        b=request.get_json(silent=True) or {}
        if set(b)!=set(('STORAGE_LIMIT','SHARE_LIMIT')) or any(type(v) is not int or not 1<=v<=1024**5 for v in b.values()) or b['SHARE_LIMIT']>b['STORAGE_LIMIT']:
            return fail('invalid_input')
        with db(True) as c:
            used=c.execute('SELECT coalesce(sum(size),0) FROM files').fetchone()[0]
            if b['STORAGE_LIMIT']<used:return fail('below_usage',409)
            for k,v in b.items():c.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,v))
            audit(c,'settings.updated')
        return jsonify(ok=True)

    @app.get('/api/admin/mail/settings')
    @protected(admin=True)
    def get_mail_settings():
        return jsonify(**app.mail_settings(),has_password=app.smtp_password_present(),allow_plain=app.config['ALLOW_INSECURE_SMTP'])

    @app.put('/api/admin/mail/settings')
    @protected(admin=True)
    def set_mail_settings():
        try:
            config,password,clear=validate_settings(request.get_json(silent=True),app.config['ALLOW_INSECURE_SMTP'])
        except ValueError as e:return fail(str(e))
        app.save_mail(config,password,clear)
        with db(True) as c:audit(c,'mail.settings_updated')
        return jsonify(ok=True)

    @app.post('/api/admin/mail/test')
    @protected(admin=True)
    def test_mail():
        body=request.get_json(silent=True) or {}
        recipient=body.get('recipient','')
        language=body.get('language','en')
        if not address(recipient) or language not in ('fr','en'):return fail('invalid_input')
        if not app.mail_settings()['enabled']:return fail('smtp_disabled',409)
        if not rate_limit('smtp-test:'+str(g.user['id']),10):return fail('rate_limited',429)
        with db(True) as c:
            job=app.enqueue_mail(c,g.user['id'],recipient.lower(),language,kind='test')
            audit(c,'mail.test_queued',str(job))
        return jsonify(id=job,status='pending'),202

    @app.patch('/api/admin/mail/copies')
    @protected(admin=True)
    def mail_copies():
        body=request.get_json(silent=True) or {}
        if set(body)!={'cc','bcc'}:return fail('invalid_input')
        try:copies={k:addresses(body[k]) for k in ('cc','bcc')}
        except ValueError:return fail('invalid_input')
        config=app.mail_settings()
        config.update(copies)
        app.save_mail(config,'')
        with db(True) as c:audit(c,'mail.settings_updated')
        return jsonify(ok=True)

    @app.post('/api/shares/<sid>/notify')
    @protected()
    def notify_share(sid):
        body=request.get_json(silent=True) or {}
        try:recipients=addresses(body.get('recipients',[]))
        except ValueError:return fail('invalid_input')
        language=body.get('language','en')
        if not recipients or language not in ('fr','en'):return fail('invalid_input')
        if not app.mail_settings()['enabled']:return fail('smtp_disabled',409)
        if not rate_limit('notify:'+str(g.user['id']),20):return fail('rate_limited',429)
        with db(True) as c:
            share=c.execute('SELECT * FROM shares WHERE id=? AND owner=?',(sid,g.user['id'])).fetchone()
            if not available(c,share):return fail('not_found',404)
            if not c.execute('SELECT 1 FROM files WHERE share_id=? AND ready=1',(sid,)).fetchone():return fail('no_files',409)
            jobs=[app.enqueue_mail(c,g.user['id'],r,language,sid) for r in recipients]
            audit(c,'mail.share_queued',sid)
        return jsonify(ids=jobs,status='pending'),202

    @app.get('/api/mail/jobs')
    @protected()
    def mail_jobs():
        with db() as c:
            rows=c.execute('SELECT id,share_id,recipient,language,kind,status,attempts,created,updated,error FROM mail_jobs WHERE owner=? ORDER BY id DESC LIMIT 100',(g.user['id'],)).fetchall()
        return jsonify(jobs=[dict(r) for r in rows])

    @app.get('/api/admin/mail/jobs')
    @protected(admin=True)
    def admin_mail_jobs():
        with db() as c:
            rows=c.execute('SELECT m.id,m.share_id,m.recipient,m.language,m.kind,m.status,m.attempts,m.created,m.updated,m.error,u.email AS owner FROM mail_jobs m LEFT JOIN users u ON u.id=m.owner ORDER BY m.id DESC LIMIT 200').fetchall()
        return jsonify(jobs=[dict(r) for r in rows])

    @app.post('/api/admin/mail/jobs/<int:jid>/retry')
    @protected(admin=True)
    def retry_mail(jid):
        if not app.mail_settings()['enabled']:return fail('smtp_disabled',409)
        if not rate_limit('mail-retry:'+str(g.user['id']),20):return fail('rate_limited',429)
        with db(True) as c:
            if not c.execute("UPDATE mail_jobs SET status='pending',error=NULL,updated=? WHERE id=? AND status='failed'",(int(time.time()),jid)).rowcount:return fail('invalid_input',409)
            audit(c,'mail.retried',str(jid))
        return jsonify(ok=True),202

    @app.get('/api/admin/system')
    @protected(admin=True)
    def get_system_settings():
        return jsonify(system_settings())

    @app.patch('/api/admin/system')
    @protected(admin=True)
    def update_system_settings():
        body=request.get_json(silent=True) or {}
        with db(True) as c:
            current=system_settings(c)
            if not body or set(body)-set(current):return fail('invalid_input')
            value={**current,**body}
            if not isinstance(value['application_name'],str) or not 1<=len(value['application_name'].strip())<=80 or any(ord(x)<32 for x in value['application_name']):return fail('invalid_input')
            if not isinstance(value['login_message'],str) or len(value['login_message'])>400:return fail('invalid_input')
            if not isinstance(value['application_url'],str):return fail('invalid_input')
            try:
                url=urlsplit(value['application_url'])
                port=url.port
            except ValueError:return fail('invalid_input')
            if url.scheme not in ('http','https') or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('','/') or any(x.isspace() for x in value['application_url']):return fail('invalid_input')
            value['application_url']=value['application_url'].rstrip('/')
            value['application_name']=value['application_name'].strip()
            if value['default_language'] not in ('fr','en') or type(value['require_share_password']) is not bool:return fail('invalid_input')
            if any(type(value[k]) is not int for k in ('default_days','max_days','default_downloads','session_hours')):return fail('invalid_input')
            if not 1<=value['default_days']<=value['max_days']<=365 or not 0<=value['default_downloads']<=100000 or not 1<=value['session_hours']<=168:return fail('invalid_input')
            c.execute('INSERT INTO system_config VALUES(1,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value',(json.dumps(value),))
            if value['session_hours']<current['session_hours']:
                c.execute('UPDATE sessions SET expires=min(expires,?)',(int(time.time())+value['session_hours']*3600,))
            audit(c,'system.updated',','.join(sorted(body)))
        return jsonify(ok=True)

    @app.post('/api/admin/database-backup')
    @protected(admin=True)
    def database_backup():
        if not rate_limit('backup:'+str(g.user['id']),3):return fail('rate_limited',429)
        with db() as c:
            size=c.execute('PRAGMA page_count').fetchone()[0]*c.execute('PRAGMA page_size').fetchone()[0]
            if size>32*1024**2:return fail('backup_too_large',413)
            # Use a standalone DELETE-journal snapshot: a serialized WAL-mode
            # in-memory database can otherwise require non-existent sidecars.
            with tempfile.TemporaryDirectory(prefix='.database-export-',dir=root) as folder:
                path=Path(folder)/'snapshot.sqlite'
                target=sqlite3.connect(path)
                try:
                    c.backup(target)
                    target.execute('PRAGMA journal_mode=DELETE')
                    for transient in ('oidc_flows','oidc_pending'):
                        if target.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(transient,)).fetchone():target.execute('DELETE FROM '+transient)
                    target.commit()
                finally:target.close()
                if path.stat().st_size>32*1024**2:return fail('backup_too_large',413)
                data=path.read_bytes()
        with db(True) as c:audit(c,'database.exported')
        return send_file(io.BytesIO(data),as_attachment=True,download_name='passelio-database-'+time.strftime('%Y%m%d-%H%M%S',time.gmtime())+'.sqlite',mimetype='application/octet-stream')

    init_storage(app,db,root,protected,fail,audit,rate_limit)
    init_transfers(app,db,root,blobs,protected,fail,audit,current_limits)
    init_upload_requests(app,db,protected,fail,audit,rate_limit)
    init_accounts(app,db,root,protected,fail,audit,rate_limit)
    init_account_policy(app,db,protected,fail,audit,rate_limit)
    init_insights(app,db,protected,fail,audit)
    init_mfa(app,db,root,protected,fail,audit,rate_limit)
    init_identity(app,db,root,protected,fail,audit,rate_limit)
    init_backup_manager(app,db,root,protected,fail,audit,rate_limit)
    init_branding(app,db,root,protected,fail,audit)
    return app
