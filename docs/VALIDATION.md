# Alpha validation — 17 November 2026

## Completed checks

- Eight pytest scenarios: upload/download SHA-256 round trip with a share password; revocation and physical cleanup; owner isolation; administrator-only user creation; CSRF/Origin enforcement and path traversal rejection; global and per-share quota enforcement; expiry and persistence; atomic concurrent download allowance and quota reservations; session invalidation after password change; saved language preference; login throttling and response headers; identical French/English translation key sets.
- JavaScript syntax checked with Node.
- French and English UI checked in a browser using a disposable local demonstration account. Responsive narrow layout inspected. Original SVG logo included; no external fonts or third-party image requests.
- Docker image built on Linux with pinned Python base digest and exact Python dependency versions.
- Docker Compose startup tested with read-only root filesystem, dropped capabilities, non-root UID 10001, named persistent volume and mounted bootstrap secret.
- A 3,000,000-byte test file was uploaded and downloaded through the container HTTP API. SHA-256 matched. Share metadata and password protection remained present after application-container restart.
- Disposable remote test containers and volume removed after verification. No NPM route or public service was created for Passelio; Erugo remained separate.

## Limits of this evidence

This is not an independent security audit. Browser interaction tests do not yet cover every workflow, assistive technology or mobile device. Large-file, low-bandwidth, abrupt-process termination and sustained-load testing remain required. No SMTP test is applicable because email is not implemented in this alpha. No claim of complete Erugo feature parity is made.

GitHub Actions is configured to repeat Python tests, JavaScript syntax checking and Docker construction. Its remote outcome must be inspected after pushing; the presence of a workflow file is not evidence that a run passed.


## Administration extension (alpha.2)

Twelve pytest scenarios pass after the extension. Additional coverage includes admin-only access to every administrative API, CSRF enforcement, account disabling and session invalidation, blocked login for disabled users, role changes, self-demotion protection, persisted quota changes across application instances, increased upload limits, administrative share revocation, audit events and migration of an existing users table.

The French and English administration screens were checked in the browser: overview, users and settings. Existing local preview data was copied with the server stopped before restarting on a persistent preview directory. The existing Erugo instance was not modified.

## SMTP extension (alpha.3)

Twenty-two pytest cases pass after adding the mail subsystem. A disposable loopback SMTP server receives French/English share notifications, verifies CC envelope recipients and absence of BCC headers, and confirms that share passwords are never included. Explicit test emails exclude automatic CC/BCC. Further cases cover password redaction/preservation/removal, blocked plaintext by default, header/template validation, safe authentication/certificate/sender/rejection/timeout errors, explicit retries, owner isolation, CSRF, cancellation after revocation and verified STARTTLS contexts.

The SMTP administration labels were checked in the browser after fixing startup ordering: all language dictionaries load before initial rendering, and missing translations no longer replace field labels with a misleading generic error. Translation tests cover every static data-i18n label across all three JavaScript modules. No real SMTP credentials or real recipients were used during validation.

The background outbox process is enabled in the local preview. Actual delivery through a chosen external SMTP provider remains an operator test requiring that provider's settings and an explicit test recipient. SMTP acceptance is not proof of inbox delivery.

## Grouped settings extension (alpha.4)

Four additional tests cover persisted branding/link settings, public configuration redaction, server-side expiry/password/download defaults, session lifetime reduction, admin/CSRF restrictions, malformed origin settings, automatic copies and a restorable SQLite snapshot. The initial snapshot test caught a WAL-mode serialization problem; export now uses SQLite's backup API into a standalone DELETE-journal file. The exported bytes deserialize successfully and pass integrity_check.

The full pre-fix suite had 25 passing cases and the snapshot failure; all four focused system tests pass after the fix. CI reruns all 26 cases on the final commit. Browser checks confirmed French/English system labels, the General form/help layout, notification-copy controls and integrated SMTP panel. No real company screenshots or user lists are included in the repository; docs/FEATURE_MATRIX.md records the functional inventory without those assets.

## Visual identity extension (alpha.5)

Four additional automated cases cover raster upload/re-encoding, public image delivery, activation, persistence after app recreation, deletion/reference reset, role/CSRF checks, SVG/HTML/oversized input rejection, typed asset references, background selection, separate asset accounting, strict data-only themes and contrast rejection. These four tests and the expanded five-module translation-key/static-label check pass locally. CI runs the full 30-case suite and builds the updated Docker image with pinned Pillow.

Browser checks cover the French and English visual-identity controls and actual application of the Ocean preset. The original Midnight preset was restored afterward. No corporate logo or screenshot was imported; tests use generated raster data. Videos/animations, uploaded SVG and arbitrary CSS themes are not supported.

## Erugo palette choices (alpha.6)

Fourteen upstream bundled palette references are adapted with MIT attribution alongside the three existing presets. Two added tests assert the full choice list, validate every preset, check dark/gradient palette export/import and reject URL-valued gradient endpoints. The six branding cases and translation/static-label check pass locally. CI reruns all 32 tests and Docker construction.

Browser checks exercised Dracula dark-mode inputs/buttons/text and the Erugo 2026 gradient. The previously selected Amber preset was restored. Existing user-uploaded preview assets were left untouched and are not committed. Screenshot proof is kept only in ignored local preview files. Source palette data and the upstream license are included under third_party.

## Alpha.7 accounts, transfers and synchronization

Added regression cases cover recovery enumeration responses, single-use expiry, session invalidation, invitation authorization, profile validation, superseded mail cancellation, resumable offsets/quota/path enforcement/cleanup, upload-only request isolation/revocation, ZIP folder contents, message template allowlists/idempotency, statistics and full backup/restore/checksums/path validation. Static snapshots pair the frontend with the running backend; a test proves newly edited scripts cannot leak into an old process. Translation tests send source through Node stdin to avoid the Windows command-line length limit.

The reported login error was reproduced as HTTP 404 on /api/me/profile from an alpha.6 process serving an alpha.7 script. The preview has been restarted with matching APIs and a browser login verified both administration and the home screen without an error notice. Preview screenshots and company assets remain ignored. No external production emails were sent; SMTP tests use a local fake server.

## Alpha.8 MFA and retained backups

New cases use RFC 6238 SHA-1 reference vectors, session invalidation, TOTP replay rejection, concurrent logins, hashed single-use recovery codes, enrollment expiry and authorization, password-recovery/MFA separation and full-backup restoration of active factors. Backup-manager cases exercise queueing, worker leases, retention, authenticated downloads, preserved last-good archives on failure, generic error redaction and restored schedules being disabled.

The tests caught a Flask endpoint-name collision while wiring the backup manager; its endpoints now have distinct names. Browser checks do not enable MFA or backups on the user's demo account. No external SMTP or identity provider is contacted by these tests.

The backup-worker tests also caught request-only audit context access; system audit events now explicitly record a null actor outside HTTP requests. Full backups hard-link immutable blobs/assets in private staging and release the writer lock before streaming archives. SMTP secret/config updates now share the backup snapshot lock.

## Alpha.9 S3 and SFTP storage

57 automated cases pass locally. New tests cover remote file/ZIP streaming, password gates, local spool removal, remote cleanup, full remote-inclusive restore, failed resumable finalization/retry, destination identity guards, mixed local/remote data, backup pins and API redaction. SDK tests exercise Boto3 upload/head/get/delete/head-bucket through Stubber. A real Paramiko loopback server exercises SFTP password authentication, pinned host key, exclusive temporary upload, chmod, rename, stream, repeated deletion and unknown-host rejection. No live external provider or company SFTPGo account is contacted.

Upload completion status now recognizes an already completed file after a lost HTTP response, avoiding duplicate publication on retry. Full backup source records are normalized to local destinations for restore, and object deletion queues/bindings/pins are excluded from the archive. New source/credential examples contain only invalid example hosts and private mount paths.

## Alpha.10 interface storage configuration

All 63 tests pass locally. Six new cases cover admin/CSRF/password/MFA enforcement, SFTP password and encrypted-SSH-key configuration, secret preservation/redaction, staged-secret cleanup on failed connection tests, in-use identity guards, stale runtime bindings, concurrent revision rejection, S3 field validation, multi-process hot refresh and restore resetting GUI settings. Existing SDK/real-loopback-SFTP and transfer/backup tests continue to pass. No real external credentials or storage destination were configured in the preview.


## Alpha.11 account lifecycle and distribution

All 77 cases pass locally, including the Microsoft single-tenant case; Google/Microsoft token exchange is mocked with real signed RS256 tokens. Tests cover explicit linking, no email auto-linking, state/nonce/issuer/audience/expiry, flow replay, local MFA/CSRF, registration ownership, single-use verified email changes, session revocation, individual quota reservation, sanitized multipart email and upload-only request notifications. CI reruns the final suite, dependency audit, JavaScript syntax, Docker build and isolated concurrency check.

`python scripts/load_check.py` passed eight concurrent 1 MiB upload/download transfers with matching SHA-256 checksums (0.86 seconds on the development machine). This is a Flask-client smoke benchmark, not a production HTTP, reverse-proxy or capacity certification.

An isolated SFTPGo v2.7.6 container passed pinned-host-key connection checks, 1,480,000-byte upload/download SHA-256 verification and repeated deletion. No existing SFTPGo accounts or company backup data were modified; the temporary container was removed.

Live S3 testing was completed on 2026-11-19 against an isolated SeaweedFS server through a TLS-verified Nginx endpoint and an SSH tunnel. Single-part (1 MiB) and multipart (9 MiB) upload/download SHA-256 checks and repeated deletion passed. An application-level test also passed resumable upload, password-gated download, local spool removal, full backup/verify/local restore and remote cleanup. Both temporary containers, fixture certificates and the SSH tunnels were removed. See SECURITY-REVIEW-2026-11-19.md for scope and limitations.

Optional provider sign-in is disabled until the operator supplies their own OAuth application credentials. No real Microsoft/Google tenant login, independent security audit or public production certification has been completed. GHCR publication is performed only after CI succeeds; package visibility is separate from image creation.


## Alpha.12 home navigation and share-link email

Home now groups existing functions in a vertical navigation. A dedicated email panel selects an active owned share, copies its link and sends it through the existing authenticated SMTP outbox. Successful uploads open that panel automatically; existing shares open it from their notification action. English/French labels, empty state, creating a test upload and selecting an existing share were verified in the browser. The ten SMTP/outbox tests pass, and translation parity includes the new navigation keys. No external recipient was contacted during the UI check.
