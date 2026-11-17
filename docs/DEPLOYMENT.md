# Deployment, maintenance and backups

This guide describes the private alpha. Keep it on a trusted test network until the security and release gates in PROJECT.md are met.

## Configuration

`BASE_URL` must be the exact externally visible origin (scheme, hostname and optional port, no path), e.g. `https://files.example.com`. It is used for links and Origin checks. Set `SECURE_COOKIES=true` for HTTPS. The default `false` is only for local HTTP development. Initial administrator credentials come from `ADMIN_EMAIL` and the file named by `ADMIN_PASSWORD_FILE`; bootstrap happens only with an empty user table.

Run `docker compose build` before `docker compose up -d`, including on upgrades: the cleanup service shares the application image. Both services run as UID/GID 10001. If using a bind mount instead of the provided named volume, provision its permissions for that user. Never mount another application's data directory or share production Erugo storage.

## Nginx Proxy Manager

For a proxy on the same Docker host, join the application to a dedicated Docker network shared with NPM. Forward to its service/container name, port 8080, scheme HTTP. Keep the alpha's host port bound to loopback or remove it entirely when using Docker networking. Use a certificate covering the chosen hostname and Force SSL. Do not publish the NPM administration port.

Suggested advanced configuration (align the size with SHARE_LIMIT):

```nginx
client_max_body_size 2g;
proxy_request_buffering off;
proxy_buffering off;
proxy_read_timeout 300s;
proxy_send_timeout 300s;
```

Upload limits apply to the sum of files in a share. No real IP headers are trusted in this alpha. Rate limiting uses the direct socket peer, which may be the proxy. Do not blindly enable forwarded headers from arbitrary clients.

## Data and lifecycle

`/data/passelio.sqlite` contains accounts, session hashes, share metadata and upload reservations. `/data/files` contains opaque random blob filenames. User-provided filenames are metadata only. Cleanup runs every five minutes, deleting expired/revoked blobs and their metadata. Share metadata and audit events are retained in this alpha; plan retention before production.

The database must be on a local filesystem. Only run one application deployment. Multiple Gunicorn workers within that deployment serialize quota modifications through SQLite transactions. Do not place the database on S3/NFS or start replicas against separate databases.

## Backup and restore

Stop both services before taking a consistent backup of the entire named volume. Include the database and all files together; copying only the SQLite main file while services are running is unsafe because WAL data can be outstanding. Keep backups outside the volume and protect them as credentials and shared content are included.

1. `docker compose stop`.
2. Back up the complete `passelio_data` volume using your Docker volume backup tooling. Record the application image/version and configuration separately; keep the bootstrap secret securely.
3. `docker compose start`.
4. Test restoration into a separate, isolated deployment with the same application version. Check login, share metadata, sample downloads and SHA-256 hashes.

Never use `docker compose down -v` during a normal upgrade: it deletes persistent data. Alpha.2 adds a users.active column (default enabled for existing accounts) and a settings table automatically at startup. Back up the complete volume before upgrading. Rolling back to alpha.1 would ignore disabled-account status; restore the pre-upgrade backup if you must roll back rather than serving that database with old code.

## Crash recovery limitations

Abruptly terminated uploads may leave `ready=0` file rows and incomplete blobs. They reserve quota until share expiry/revocation and cleanup. This is conservative and prevents over-allocation. Inspect only while services are stopped; do not delete rows/files from an active upload. Do not automate stale-upload deletion based only on an arbitrary timeout: a valid long transfer may still be active.

## Checks

`GET /api/health` returns version and status without credentials. Docker health checks test HTTP availability. It does not establish that every background operation or backup works. Read cleanup process logs separately. Passwords, session cookies, share-password tickets and password-reset links must not be placed in logs or bug reports.


## Administration (alpha.2)

Open /admin using an administrator account. The console provides active-user/share/file counts, logical quota and real disk-free information, searchable user/share lists (up to 200 rows), and the 200 latest audit events.

Administrators can add users, assign/revoke the administrator role, disable/re-enable accounts and revoke any share. A status/role change invalidates that user's active sessions. You cannot disable/demote your own administrator account or remove the last active administrator. Disabling an account does not revoke existing public links; use the all-shares view separately.

Settings in the database override STORAGE_LIMIT and SHARE_LIMIT environment defaults and apply to every worker. Reducing the total quota below current reservations/usage is rejected. Reducing the per-share limit does not delete existing files. The interface uses GiB/Gio; the API stores integer bytes. A quota change never provisions or resizes a disk.

Audit metadata includes actors, action types and target identifiers, not passwords or session tokens. Administrators can see other users' share metadata, but the console does not bypass share-password checks or provide direct file downloads. Account deletion, SMTP configuration, branding and antivirus controls are not implemented in this release.
