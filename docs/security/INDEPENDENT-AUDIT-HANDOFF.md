# Passelio — independent review handoff

Status (25 November 2026): handoff prepared for later review, as requested by the owner. No auditor has been appointed, no external recipient has received access and no paid engagement has been authorized. The application is not independently certified. A private Unraid trial is running; no public release is approved.

## Concrete review target

- Runtime source revision: `a82968ef774e0d716fcfe850d46c73772f5d66f2`, with subsequent documentation and integration-harness updates.
- Validated application image: alpha.15, `ghcr.io/pasqual51/passelio@sha256:a20c6244196a4332774c6fca6b886bb565ffd9be496fcab34c58f53600598526`.
- Repository: private `pasqual51/passelio`, AGPL-3.0-only. Grant a named assessor the minimum access only after the owner selects the assessor and scope.
- Run two isolated containers against fresh test data, never against company production services. Provide synthetic accounts, files, a test SMTP sink and disposable storage credentials. Do not include bootstrap secrets, session cookies, live share capabilities, production backups or corporate visual assets in the handoff.

## Architecture and trust boundaries

The web process is Flask/Gunicorn with SQLite metadata, server-side sessions, CSRF and rate limiting. A separate worker handles SMTP, expiry/deletion and backups. File storage supports local data, administrator-configured S3 and pinned-host-key SFTP. External upload requests are scoped capabilities. Google/Microsoft OIDC requires explicit linking; local TOTP remains required when enabled.

The browser, anonymous share/upload recipients, ordinary users, application administrators, storage providers and the Docker/host operator have distinct trust levels. Administrator storage configuration intentionally reaches operator-selected internal endpoints; review privilege boundaries and avoid incorrectly treating authorized configuration as an anonymous URL-fetch API. The host, mounted data volumes and offline restore operator are trusted. No end-to-end encryption is claimed.

## Requested independent work

1. Review session issuance/revocation, CSRF/origin checks, brute-force controls, password recovery, email ownership, registration, OIDC state/nonce/claims/linking and TOTP/recovery-code replay behavior.
2. Attempt cross-user access, capability confusion, upload-request download access, password/expiry/download-limit bypass, traversal and filename/XSS/header injection.
3. Review resumable uploads, quota reservations/concurrency, interrupted transfers, object routing, destination changes, deletion leases/pins and remote errors.
4. Assess SMTP templates, recipient/CC/BCC semantics, secret redaction, active links in messages and error/audit/outbox retention.
5. Review backup consistency, archive validation, resource-exhaustion limits, secret inclusion, offline restore and schema trust. Explicitly assess the SQLite FTS5/session advisories against actual reachable paths.
6. Validate Docker hardening, reduced runtime package set, package-manager removal, UID/permissions, private bind mounts and platform behavior on Unraid. Confirm no unintended host mounts, Docker socket access or public administration exposure.
7. Reassess all thirteen high advisory IDs in the alpha.15 scan independently (44 package/advisory matches). This supersedes the eleven-ID alpha.14 baseline. Separate absent vulnerable components from retained affected libraries and privilege-precondition mitigations. Do not equate scanner severity, duplicate package matches or a successful CI job with demonstrated web exploitability or safety.
8. Test realistic large-file transfers and interruption/restart behavior within agreed resource limits. Public-network scanning, denial-of-service tests, external SMTP delivery and tests of third-party services require an explicit scope from the owner.

## Existing evidence

- [Per-advisory analysis and before/after scan](HIGH-FINDINGS-TRIAGE-2026-11-19.md), including exact image and CSV.
- [Earlier image review](IMAGE-REVIEW-2026-11-19.md), [internal review](../SECURITY-REVIEW-2026-11-19.md) and [validation log](../VALIDATION.md).
- [Successful alpha.14 CI](https://github.com/pasqual51/passelio/actions/runs/44479152264): 82 tests, syntax/dependency checks, Docker build, full unsuppressed image scan and non-root/no-network/read-only runtime checks, including backup/restore.
- [Successful alpha.15 CI](https://github.com/pasqual51/passelio/actions/runs/45584153925): 84 tests, dependency/syntax/build checks, image scan and hardened-runtime smoke test. Preserve artifact `passelio-candidate-security` (ID `15007901979`). It reports no critical, Python-package, embedded-secret or fixed-version publication blockers, but retains 44 high package/advisory matches across 13 IDs. This is not a clean-security certification.
- [25 November integration validation](../VALIDATION-2026-11-25.md): real SeaweedFS and OpenSSH services, verified TLS/host keys, local/S3/SFTP transfers and retained backups, real-clock TOTP and recovery, private SMTP delivery and isolated restoration. The reproducible application-side checks are in `scripts/integration_unraid.py`. These are developer-run integration checks, not an independent assessment.
- Full CI artifacts expire after 30 days; preserve the required artifacts privately before an engagement. Normalized findings and source remain versioned in the repository.

## Required deliverable and release decision

Ask the assessor for reproducible findings, affected revision/image digest, severity rationale, prerequisites, exploit evidence where appropriate, recommended remediation and a remediation retest. The owner must decide the residual risk and supported deployment scope after remediation; the developer cannot self-declare an independent sign-off. Until then, keep the instance on the agreed private test network.
