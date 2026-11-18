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


## Extended theme palettes (alpha.6)

Seventeen presets are now available: the three original Passelio palettes plus fourteen Erugo 0.2.15 palette adaptations, with upstream MIT license/attribution shipped in third_party. No upstream arbitrary CSS is interpreted. The visual reference JSON contains color data, not company-specific settings or user assets.

Theme JSON still requires name and colors with primary, accent and background. Optional supported hex-only roles are surface, text, muted, subtle, border, primary_text, primary_end and background_end. Other fields are rejected. Three-color themes remain compatible with alpha.5. Extended palettes validate text, muted and accent contrast across page/card/subtle surfaces, and primary text against gradient endpoints. The source adapter adjusts colors when required. This is not a certification of arbitrary artwork or every visual state.

The API exposes original color roles and a resolved palette for rendering. Imported/exported extended themes retain all supported roles, even though the basic editor exposes only the three main colors. To edit/remove advanced roles, edit the exported JSON; CSS and URLs remain forbidden. The application creates gradients only from validated color endpoints and adapts cards/inputs/tables/header to light or dark mode. Local theme tests restore the previous selection afterward.

## Accounts and transfers (alpha.7)

Invitation/reset delivery requires enabled SMTP. Account links use the configured trusted application URL, a fragment token (not sent in HTTP request paths), one-hour reset/24-hour invitation expiry and single-use redemption. Resetting a password invalidates sessions. Keep account-signing-key private and persistent in the data volume; the SQLite export alone does not include it. Disabled users cannot redeem links. Account emails do not receive automatic CC/BCC copies. Templates are plain text with an allowlist of variables. Recovery responses do not disclose account existence.

Resumable uploads reserve their full size against quotas, accept at most 8 MiB per chunk and expire after 24 hours without activity. The authenticated browser keeps local resume metadata and verifies previously uploaded chunk hashes when the same files are selected again. This is not the tus protocol. Upload-only request links are bearer capabilities: anyone holding the link can contribute within the owner's quotas until expiry/revocation, but cannot list or download the collection. Review quota and exposure before distributing links. Public request uploads currently restart from scratch after a browser interruption.

ZIP downloads preserve validated relative paths and count as one download request. They require temporary local disk space for the archive. Empty folders are not represented. File and ZIP requests count requests, not proof that a complete download reached the recipient.

## Full backup and offline restore

The backup CLI includes completed file blobs, visual assets, the SQLite snapshot and installation secrets. Treat the archive as confidential; transfer/store it using your normal encrypted backup system. Backups are not encrypted by Passelio. Sessions, download tickets, account actions and incomplete uploads are excluded. Do not publish an archive in the source repository.

```sh
python backup.py create --data /data --output /backup/passelio-20261118.zip
python backup.py verify --archive /backup/passelio-20261118.zip
python backup.py restore --archive /backup/passelio-20261118.zip --target /new-data
```

Mount /backup separately and ensure the container UID can write it. Creation holds the database writer lock while snapshotting SQLite and hard-linking immutable completed blobs/assets into a private staging directory inside DATA_DIR, then releases it before streaming the ZIP. The data filesystem must support hard links. Uploads/cleanup may wait briefly while the snapshot inventory is created. Restore only while app and worker are stopped, into a nonexistent target directory; switch the deployment volume after verification. The restore CLI validates the inventory, paths, sizes, SHA-256 checksums and SQLite integrity. It never overwrites an existing data directory. Restored archives use local storage. Scheduled retention is available from alpha.8; S3/SFTP source data is included from alpha.9. See STORAGE.md for remote configuration and backup requirements.

## Two-factor authentication (alpha.8)

In My profile, enter the current password to start authenticator enrollment. Add the displayed Base32 secret manually to a compatible TOTP application (SHA-1, six digits, 30 seconds), then confirm a code within ten minutes. No third-party QR service receives the secret. Successful activation revokes all sessions and displays ten recovery codes exactly once. Store them in a password manager before returning to sign-in. A just-used authenticator code cannot be reused; wait for the next code. Clock drift tolerance is one step either side, with atomic replay prevention across workers.

Disabling MFA requires the current password plus an unused TOTP or recovery code and revokes sessions. Email recovery changes only the password; it does not disable MFA. There is no administrator bypass in the web interface. Keep an independent active administrator and protect full backups before enabling MFA on production accounts. Lost authenticator and recovery codes require controlled operator recovery; this alpha does not offer an automatic bypass. Secret files under mfa-secrets are private installation data, never publish them or include them in plain database exports. Full backup archives include active secrets and must remain confidential. Restoring an old full backup also restores its MFA/recovery-code state; review authenticator enrollment and recovery codes after restore.

## Scheduled backups (alpha.8)

The Compose app and worker now share a separate passelio_backups named volume mounted at /backups (BACKUP_DIR). This separates archives from application data logically; it is still on the same Docker host unless you configure an independent storage mount. Do not treat it as an off-site backup. For existing installations, rebuild the image and recreate both services so the writable mount and ownership exist. Keep the data volume and credentials unchanged.

In Administration → System settings → Database backup, queue a full backup or enable a daily/weekly interval and retention of 1–14 archives. New schedules first run after the selected interval; use the immediate queue button for the first archive. The worker claims jobs atomically. A crashed worker lease can delay another attempt for up to 24 hours. Failed creation preserves prior verified archives and reports a generic error; retention is applied only after a new archive is verified and registered. File-system permission failures may leave extra retained archives for an operator to review. No archive is exposed through public share routes.

Archives contain credentials and are not encrypted by the application. Protect the backup mount and copy verified archives to a separate encrypted backup system. Keep enough space for retained archives plus the next full archive and database snapshot; quotas on shared files do not reserve backup space. Restoring a full archive resets automatic schedules and its archive inventory to avoid running old scheduled jobs unexpectedly. Configure the schedule again after validating the restored installation.

## Remote file destinations (alpha.9)

See [STORAGE.md](STORAGE.md) before enabling S3 or SFTP. Supply the same STORAGE_CONFIG_FILE and read-only credential/trust mounts to app and worker. Existing local files remain local; new files use the configured default. Destination identity changes are rejected while files or deletion jobs refer to that destination. Do not remove a required configuration mount during an update. Restart both services after changing deployment configuration.

Full backups include remote bytes and restore into a self-contained local directory, excluding source deletion jobs and remote bindings. Provider credentials are deployment-owned and are not bundled into the archive. Remote cleanup is deferred and retried by the worker, with backup pins preventing deletion during a snapshot. The read-only storage check does not verify write permissions. SFTP requires a preverified known_hosts entry; no auto-trust or TLS-validation bypass is provided. No real SFTPGo account, bucket or remote data has been modified by development/testing.
