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

Audit metadata includes actors, action types and target identifiers, not passwords or session tokens. Administrators can see other users' share metadata, but the console does not bypass share-password checks or provide direct file downloads. Account deletion, branding and antivirus controls are not implemented in this release.


## SMTP notifications (alpha.3)

Run exactly one background service (the compose cleanup service also processes the outbox every five seconds). No email is sent merely by saving settings. SMTP tests require an explicit recipient/action and do not use automatic CC/BCC. Share notification requests require share ownership and at least one completed file; one job per recipient is queued with the selected French/English language. Limit: 20 recipients per request, 20 notification requests per user per 15 minutes. CC and BCC support 20 addresses each and apply to every share notification. Inform users that automatic copies are configured; copies contain the share link.

STARTTLS and implicit TLS validate server certificates and hostnames. There is no certificate-validation bypass. Plain SMTP is rejected unless ALLOW_INSECURE_SMTP=true is explicitly set for a disposable local test environment. Do not use that setting with real credentials or an Internet deployment. Custom internal certificate authorities must be provisioned into the container's trusted CA store rather than disabling validation.

The SMTP password is stored in the application-owned /data/smtp-password file with mode 600, separately from JSON configuration, and is never returned by APIs. This is access-controlled storage, not encryption at rest; protect the whole data volume and encrypted backups. Other SMTP settings, recipients and delivery metadata are stored in SQLite. The UI never exposes the password, exception text or SMTP dialogue. Changing the saved password requires entering it again; leaving it blank keeps the current one unless explicit removal is selected.

Queue states are pending, sending, sent and failed. Sent means accepted by the upstream SMTP server, not delivered to an inbox. There is no automatic retry: administrators may retry failed jobs explicitly after inspecting safe error codes. An interrupted sending job is marked failed after five minutes when the worker runs again. Partial acceptance, interrupted SMTP sessions and manual retries can create duplicates. This alpha does not guarantee exactly-once delivery or process bounces. Changing SMTP settings affects jobs when they are processed, not when queued.

Templates use only the supported dollar placeholders title, url, sender and expiry; url must remain in each message body. Templates are plain text, not executable code or HTML. Share passwords and file contents are never included. Disabling an account or revoking/expiring a share cancels its pending notifications at processing time. Revocation cannot retract already accepted messages. The outbox retains recipient addresses and events; define a retention policy before production.


## Grouped system settings (alpha.4)

The system_config table is added automatically on upgrade. It stores branding text, link origin, default language, expiry/download defaults, mandatory share-password policy and session lifetime. Values are validated on the server and shared by all workers. Public /api/config exposes non-secret presentation/share policy values, not session configuration or SMTP secrets. The configured application URL determines new share/email links; the original BASE_URL and configured link origin are accepted for Origin checks. Updating the URL does not provision DNS, certificates or proxy routes.

New shares enforce default/max expiry (1–365 days) and optionally require a share password of at least 8 characters. Existing shares remain unchanged. Account passwords still require 14 characters. Session lifetime is 1–168 hours; reducing it caps existing sessions, increasing it only affects future logins.

The database export uses SQLite's backup API into a standalone DELETE-journal snapshot, avoiding inconsistent copies of a live WAL database. It is administrator-only, CSRF-protected, limited to three requests per 15 minutes, and capped at 32 MiB before and after backup. The snapshot contains password hashes, share links and mail metadata; protect it. It excludes uploaded blobs and the SMTP password file, so it is not a full disaster-recovery backup. Full-volume backup/restore instructions above remain applicable.


## Visual identity (alpha.5)

The image-processing dependency Pillow is pinned. Custom branding assets are PNG/JPEG/WebP only: 5 MiB input, 20 million pixels, one frame, bounded output dimensions, re-encoded PNG without metadata. Logo/favicons/backgrounds are stored under /data/branding with server-generated identifiers. They are intentionally public by identifier; do not upload confidential images. Imported SVG, animation and video are rejected. A separate budget of 12 assets / 32 MiB and a physical free-space check prevent uncontrolled visual-asset growth; these bytes are not included in the logical share quota.

branding_config and branding_assets tables are created automatically. Deleting an asset removes its file and clears references atomically at the database level. Include images in a full-volume backup; SQLite export includes metadata/settings but not the image files.

Theme JSON contains only name and three hex colors (primary, accent, background). Unknown fields, CSS, URLs and executable templates are rejected. Main foreground/button contrast is checked at 4.5:1; this is not a full accessibility certification of every custom page or image. Presets are Midnight, Ocean and Amber. Rotation supports off/1/3/5/10/30 minutes and respects reduced-motion preferences. No external font/image service is used.
