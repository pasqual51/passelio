"""Passelio private alpha. Local storage, explicit server-side sessions."""
import hashlib
import os
import secrets
import shutil
import sqlite3
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, g, jsonify, request, send_file
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash


def create_app(config=None):
    app = Flask(__name__, static_folder="static")
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

    def audit(c, action, target=None):
        c.execute("INSERT INTO audit(created,user_id,action,target) VALUES(?,?,?,?)",
                  (int(time.time()), g.get("user", {}).get("id"), action, target))

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
            rows = c.execute("SELECT files.id FROM files JOIN shares ON shares.id=files.share_id "
                             "WHERE shares.revoked=1 OR shares.expires<=?", (time.time(),)).fetchall()
            for row in rows:
                (blobs / row["id"]).unlink(missing_ok=True)
                c.execute("DELETE FROM files WHERE id=?", (row["id"],))
            c.execute("DELETE FROM sessions WHERE expires<=?", (time.time(),))
            c.execute("DELETE FROM tickets WHERE expires<=?", (time.time(),))
        return len(rows)

    app.cleanup = cleanup
    app.db = db

    @app.cli.command("cleanup")
    def cleanup_command():
        print(f"Removed {cleanup()} expired/revoked files")

    @app.before_request
    def check_origin():
        if not (request.method == 'POST' and request.path.startswith('/api/shares/') and request.path.endswith('/files')):
            request.max_content_length = 16384
        else:
            request.max_content_length = current_limits()['SHARE_LIMIT']
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("Origin")
            if origin and origin != app.config["BASE_URL"].rstrip("/"):
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
    def index(share_id=None):
        return app.send_static_file("index.html")

    @app.get("/api/health")
    def health():
        return jsonify(status="ok", version="0.1.0-alpha.2")

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
        if not check_password_hash(stored, password) or not user or not user['active']:
            return fail("invalid_credentials", 401)
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with db(True) as c:
            c.execute("INSERT INTO sessions VALUES(?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), user["id"], csrf, int(time.time()) + 43200))
        response = jsonify(ok=True)
        response.set_cookie("passelio_session", token, max_age=43200, httponly=True, secure=app.config["SECURE_COOKIES"], samesite="Strict")
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
        title, password = b.get("title", ""), b.get("password", "")
        try:
            days, limit = int(b.get("days", 7)), int(b.get("max_downloads", 0))
        except (ValueError, TypeError):
            return fail("invalid_input")
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 150 or not isinstance(password, str) or len(password)>1024 or not 1 <= days <= 30 or not 0 <= limit <= 100000:
            return fail("invalid_input")
        sid = secrets.token_urlsafe(24)
        with db(True) as c:
            count = c.execute("SELECT count(*) FROM shares WHERE owner=? AND expires>? AND revoked=0", (g.user["id"], time.time())).fetchone()[0]
            if count >= 100:
                return fail("share_count", 409)
            c.execute("INSERT INTO shares(id,owner,title,created,expires,password,max_downloads) VALUES(?,?,?,?,?,?,?)",
                      (sid,g.user["id"],title.strip(),int(time.time()),int(time.time())+days*86400,generate_password_hash(password) if password else None,limit))
            audit(c, "share.created", sid)
        return jsonify(id=sid, url=app.config["BASE_URL"].rstrip("/")+"/s/"+sid), 201

    @app.post("/api/shares/<sid>/files")
    @protected()
    def upload(sid):
        size = request.content_length
        name = request.args.get("name", "")
        if size is None or size <= 0 or not name or len(name)>240 or any(ord(x)<32 for x in name) or "/" in name or "\\" in name or name in (".", ".."):
            return fail("invalid_input")
        fid = secrets.token_hex(24)
        with db(True) as c:
            share = c.execute("SELECT * FROM shares WHERE id=? AND owner=?", (sid,g.user["id"])).fetchone()
            if not available(c, share):
                return fail("not_found", 404)
            share_size = c.execute("SELECT coalesce(sum(size),0) FROM files WHERE share_id=?", (sid,)).fetchone()[0]
            total = c.execute("SELECT coalesce(sum(size),0) FROM files").fetchone()[0]
            limits=current_limits(c)
            if share_size+size > limits['SHARE_LIMIT'] or total+size > limits['STORAGE_LIMIT'] or shutil.disk_usage(root).free < size+64*1024**2:
                return fail("quota", 413)
            c.execute("INSERT INTO files(id,share_id,name,size,created) VALUES(?,?,?,?,?)", (fid,sid,name,size,int(time.time())))
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
            with db(True) as c:
                share = c.execute("SELECT * FROM shares WHERE id=?", (sid,)).fetchone()
                if not available(c,share):
                    raise ValueError("share expired")
                c.execute("UPDATE files SET sha256=?,ready=1 WHERE id=?", (digest.hexdigest(),fid))
                audit(c,"file.uploaded",fid)
        except Exception:
            (blobs/fid).unlink(missing_ok=True)
            with db(True) as c:
                c.execute("DELETE FROM files WHERE id=?", (fid,))
            return fail("upload_failed", 400)
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
            if not f or not (blobs/fid).is_file():
                return fail("not_found",404)
            if s["max_downloads"] and s["downloads"]>=s["max_downloads"]:
                return fail("download_limit",410)
            if request.method != "HEAD":
                c.execute("UPDATE shares SET downloads=downloads+1 WHERE id=?",(sid,))
                audit(c,"file.downloaded",fid)
            return send_file(blobs/fid,as_attachment=True,download_name=f["name"],mimetype="application/octet-stream",conditional=False)

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
                        limits=current_limits(c),disk_free=shutil.disk_usage(root).free,version='0.1.0-alpha.2')
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
        q=request.args.get('q','')[:254].lower()
        with db() as c:
            rows=c.execute('SELECT s.id,s.title,s.created,s.expires,s.revoked,s.downloads,s.max_downloads,u.email AS owner,count(f.id) AS files,coalesce(sum(f.size),0) AS size FROM shares s JOIN users u ON u.id=s.owner LEFT JOIN files f ON f.share_id=s.id WHERE instr(lower(s.title),?)>0 OR instr(lower(u.email),?)>0 GROUP BY s.id ORDER BY s.created DESC LIMIT 200',(q,q)).fetchall()
        return jsonify(shares=[dict(r) for r in rows])

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

    return app
