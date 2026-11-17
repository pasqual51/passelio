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
