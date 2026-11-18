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
