# Passelio

**Your files. Your server. Your rules.**

An independent, Docker-first file-sharing project with a French and English interface.

**Status: public alpha, 0.1.0-alpha.16. Not production-ready.** Published for evaluation, feedback and contributions. Full Erugo feature parity is not yet reached. Licensed under AGPL-3.0-only. Versioned alpha containers are built for GitHub Container Registry; package visibility is configured separately from this repository.

## Try the public Docker image

Docker Engine and Docker Compose are required. No GitHub account, registry login
or personal access token is required:

```sh
docker pull ghcr.io/pasqual51/passelio:0.1.0-alpha.16
```

Clone this repository, copy `.env.example` to `.env`, set `ADMIN_EMAIL`, and create
`secrets/admin_password.txt` containing a random password of at least 14 characters.
On Linux, protect the host `secrets` directory with mode 700 and make the mounted
password file readable by container UID 10001 (for example mode 444 inside that
protected directory). Then start both services using the prebuilt image:

```sh
docker compose -f compose.image.yml up -d --pull always
```

Open <http://localhost:8080>. The default port is bound to loopback only. Configure
HTTPS before exposing the service beyond your trusted network. `compose.yml`
remains available for building the application from source.
See the [Unraid instructions](docs/UNRAID.fr.md) and
[deployment guide](docs/DEPLOYMENT.md).

## Implemented

- Responsive interface and original SVG logo; French/English switching and saved preferences.
- Vertical home navigation with dedicated sharing, email-link delivery, requests, email history and profile/security sections.
- Visual identity settings: validated custom logo/favicon/backgrounds, rotation, 17 theme presets, color editor and data-only theme JSON import/export.
- Initial administrator, user creation/invitations, single-use password recovery, profile names, login/logout and password changes.
- Optional TOTP two-factor authentication, replay protection and hashed one-use recovery codes.
- Dedicated bilingual administration console at /admin: overview, user roles/status, all-share revocation, storage, recent audit events and persistent quota settings.
- Multiple files/folders per share, quota-reserved resumable uploads, progress, SHA-256 checksums and ZIP downloads.
- Expiring upload-only request links for external contributors.
- Download statistics, editable bilingual account/lifecycle mail templates and opt-in lifecycle notifications.
- Full backup/verify/offline restore, administration queue, daily/weekly scheduling and retained archive downloads.
- Expiring links (configurable maximum, up to 365 days), optional share password, revocation and download-request limits.
- Persistent SQLite database; private local, S3-compatible and SFTP file destinations with per-file routing, streamed downloads, retryable cleanup and remote-inclusive full backups.
- Global, per-share and per-user quotas reserved transactionally.
- Optional email-owned registration, verified email changes and explicitly linked Google/Microsoft OIDC with local MFA.
- Sanitized HTML account/lifecycle templates and upload-request notifications; share state filters and pagination.
- Grouped system settings with help: application name/URL, login message, default language, share expiry/password policies, session lifetime and consistent SQLite export.
- Separate cleanup worker for expired/revoked files, every five minutes.
- SMTP settings, verified STARTTLS/SSL, explicit test email, editable French/English templates, per-recipient notifications with automatic CC/BCC, persistent outbox and safe delivery diagnostics.
- Non-root Docker container, CSRF protection, server-side sessions and login throttling.

## Not implemented yet

Antivirus, webhooks and end-to-end encryption. Google/Microsoft provider activation requires your own client credentials; no organization credentials are bundled. There is no end-to-end encryption or completed security audit. See [the roadmap](docs/PROJECT.md).

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
- Authenticated uploads can resume by selecting the same files again; external upload requests currently restart from the beginning. Incomplete reservations are cleaned after 24 hours of inactivity.
- Storage quota is logical file bytes, not a filesystem hard quota. Keep free space for the database, logs and backups. Uploads are refused if less than 64 MiB headroom would remain.
- All users currently see global usage. Accounts can be disabled/re-enabled and roles changed; permanent user deletion and password recovery are not implemented yet.
- Reverse-proxy deployments currently rate-limit by the direct peer IP. Forwarded client headers are intentionally not trusted; users may share a rate-limit bucket.

## Security and backups

Read [SECURITY.md](SECURITY.md) and [deployment and backups](docs/DEPLOYMENT.md). Never use real confidential files during alpha testing. Report security concerns privately to the repository owner rather than opening a public issue containing exploit details or secrets.

The reference feature inventory and remaining milestones are tracked in [FEATURE_MATRIX.md](docs/FEATURE_MATRIX.md).

The 14 adapted Erugo theme palettes retain their upstream MIT attribution in [third_party](third_party/README.md). Color families and choices are preserved, with contrast adjustments and Passelio-specific rendering.

## Remote storage

Local disk remains active unless explicitly changed. Choose and configure local, S3 or SFTP from Administration → Storage. Remote settings are tested before saving, with password reauthentication and a second factor when enabled. Stored credentials are never returned by the API; blank secret fields preserve them. Changes are picked up by the web processes and worker without a Docker restart. See [STORAGE.md](docs/STORAGE.md) for server-key verification, private bucket requirements, credential protection, backup behavior and optional operator-mounted configuration. No existing live provider has been configured automatically.

## License and operations

[GNU AGPL v3](LICENSE) (`AGPL-3.0-only`). Copyright 2026 Passelio contributors. Third-party palette notices remain in `third_party/`. Modified network deployments must provide their corresponding source as required by the license. See [accounts and SSO](docs/ACCOUNTS.md) and [upgrade/rollback](docs/UPGRADE.md).

## Private Unraid trial

A French setup guide and two native Unraid templates are available in [docs/UNRAID.fr.md](docs/UNRAID.fr.md). They pin the validated alpha.16 digest and prepare a fresh private test installation; no deployment is performed automatically. Independent-review scope and evidence are collected in [the audit handoff](docs/security/INDEPENDENT-AUDIT-HANDOFF.md).
