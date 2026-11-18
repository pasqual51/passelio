# Passelio

**Your files. Your server. Your rules.**

An independent, Docker-first file-sharing project with a French and English interface.

**Status: private alpha, 0.1.0-alpha.7. Not production-ready.** This is the first functional milestone, not full Erugo feature parity. No public container registry release exists yet. Licensing must be agreed with the owner before public distribution.

## Implemented

- Responsive interface and original SVG logo; French/English switching and saved preferences.
- Visual identity settings: validated custom logo/favicon/backgrounds, rotation, 17 theme presets, color editor and data-only theme JSON import/export.
- Initial administrator, user creation, login/logout and password changes.
- Dedicated bilingual administration console at /admin: overview, user roles/status, all-share revocation, storage, recent audit events and persistent quota settings.
- Multiple files per share, streamed uploads, progress and SHA-256 checksums.
- Expiring links (configurable maximum, up to 365 days), optional share password, revocation and download-request limits.
- Persistent SQLite database and file storage; global and per-share quotas reserved transactionally.
- Grouped system settings with help: application name/URL, login message, default language, share expiry/password policies, session lifetime and consistent SQLite export.
- Separate cleanup worker for expired/revoked files, every five minutes.
- SMTP settings, verified STARTTLS/SSL, explicit test email, editable French/English templates, per-recipient notifications with automatic CC/BCC, persistent outbox and safe delivery diagnostics.
- Non-root Docker container, CSRF protection, server-side sessions and login throttling.

## Not implemented yet

Resumable uploads, folders/ZIP downloads, upload requests, per-user quotas, S3, MFA/SSO and antivirus. There is no end-to-end encryption or completed security audit. See [the roadmap](docs/PROJECT.md).

## Try locally with Docker

Requirements: Docker Engine and Docker Compose v2. The commands below use a POSIX shell; create the same files with your editor on Windows.

```sh
cp .env.example .env
mkdir -p secrets
chmod 700 secrets
python3 -c "import pathlib,secrets; pathlib.Path('secrets/admin_password.txt').write_text(secrets.token_urlsafe(24)+'\n')"
chmod 444 secrets/admin_password.txt
docker compose build
docker compose up -d
```

Edit `ADMIN_EMAIL` in `.env` before starting. The generated password file is the initial administrator password; keep it private and never commit it. The host directory mode 700 protects it from other local users; the file must be readable by container UID 10001 through its read-only secret mount (a host-owned mode-600 file will prevent bootstrap). On Windows use a private directory with an ACL restricted to your account and Docker's service, and verify the secret is readable inside the container. Open **http://localhost:8080** and sign in. Change the password in the account panel. The bootstrap password is only used when no users exist; editing the file does not reset an existing account.

The default binding is loopback only. For an HTTPS reverse proxy, see [deployment](docs/DEPLOYMENT.md). Do not expose the alpha to the Internet without further review.

## Development and checks

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q
node --check static/app.js
```

Node is only required for the translation-key test and JavaScript syntax check, not for running the application. The Python tests cover authorization, CSRF, passwords, expiry, persistence, download limits and concurrent quota reservations.

## Languages

Use the header language selector. The first visit uses the browser language; local preference takes precedence, then the account preference on a new browser. Interface and API error messages are localized in `static/app.js`. Technical configuration uses English. [Documentation française](docs/README.fr.md).

## Operational limits

- One instance with one local SQLite database; do not deploy replicas or share SQLite over network filesystems.
- A download limit counts each file request (including failed/interrupted client transfers after admission), not unique people or complete multi-file shares. HEAD requests do not count.
- No upload resume in this alpha. Reloading or losing the connection requires retrying. The UI revokes a partially failed share when it can reach the server.
- Files from an abruptly killed upload can retain reservations. Stop the services and inspect/recover them before restarting; automatic stale-upload recovery is a later milestone.
- Storage quota is logical file bytes, not a filesystem hard quota. Keep free space for the database, logs and backups. Uploads are refused if less than 64 MiB headroom would remain.
- All users currently see global usage. Accounts can be disabled/re-enabled and roles changed; permanent user deletion and password recovery are not implemented yet.
- Reverse-proxy deployments currently rate-limit by the direct peer IP. Forwarded client headers are intentionally not trusted; users may share a rate-limit bucket.

## Security and backups

Read [SECURITY.md](SECURITY.md) and [deployment and backups](docs/DEPLOYMENT.md). Never use real confidential files during alpha testing. Report security concerns privately to the repository owner rather than opening a public issue containing exploit details or secrets.

The reference feature inventory and remaining milestones are tracked in [FEATURE_MATRIX.md](docs/FEATURE_MATRIX.md).

The 14 adapted Erugo theme palettes retain their upstream MIT attribution in [third_party](third_party/README.md). Color families and choices are preserved, with contrast adjustments and Passelio-specific rendering.
