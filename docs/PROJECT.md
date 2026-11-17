# Passelio — Project blueprint

Status: a runnable private alpha (0.1.0-alpha.1) is available on codex/initial-alpha in pull request #1. No production release or full Erugo feature parity is available. See VALIDATION.md for completed checks and remaining limits.

## Purpose

An independent, self-hosted file-sharing application for individuals and organizations. Docker-first installation; English and French documentation and interface; no dependency on a particular company, email domain or hosting provider.

Erugo is a functional reference, not a source of copied branding, assets or interface. Passelio will have its own design and implementation.

## Product identity

Working name: Passelio (trademark and package availability still to be checked before public launch).
Visual direction: midnight blue, turquoise, accessible contrast, clear typography and a distinctive file-in-flight symbol. Responsive desktop and mobile interface, keyboard navigation, screen-reader labels and reduced-motion support.

## Target capabilities

- File and folder transfers with resumable uploads, progress and integrity checks.
- Share links with expiry, optional passwords, download limits and immediate revocation.
- Upload requests for recipients without an account.
- SMTP notifications, configurable CC/BCC, editable templates and delivery diagnostics. SMTP secrets must never appear in logs or API responses; test emails require an explicit action.
- Users, roles, per-user quotas, global storage limits and administration.
- Local storage first, then S3-compatible storage.
- Automatic expiry cleanup and configurable retention; storage usage alerts.
- Audit events, backup and restore procedures, API and webhooks.
- Optional malware scanning, MFA and external identity providers in later milestones.
- Brand customization without hard-coded corporate names or domains.

## Delivery milestones and acceptance gates

### 0 — Design and technical specification

Define data model, API, upload protocol, threat model, storage accounting and UI flows. Select maintained dependencies and document decisions. Review logo/name availability. No production deployment at this stage.

### 1 — Private functional alpha

Docker Compose, persistent local storage, first-admin setup, login/logout, create/upload/download/revoke/expire a share, password protection, responsive English/French interface.
Acceptance: installation from a clean environment; persistence after recreation; authorization, expiry, path traversal and quota tests; end-to-end upload/download checksum; documented limitations.

### 2 — Reliable transfers and notifications

Resumable uploads, folder support, atomic quota reservations, download-count concurrency controls, cleanup worker, SMTP diagnostics, notifications and optional CC/BCC.
Acceptance: interrupted transfer resumes; concurrent transfers cannot bypass quota; expired data is reclaimed; SMTP failures are observable without exposing secrets; recipients and CC/BCC semantics tested.

### 3 — Administration and public beta

Account lifecycle, roles, audit trail, upload requests, backup/restore, accessible interface, documented upgrade/rollback, CI and versioned container builds.
Acceptance: restored backup works; migrations tested; unprivileged runtime; dependency/image checks; independent security review before recommending Internet exposure.

### 4 — Extensions

S3, MFA/SSO, antivirus integration, API/webhooks and optional end-to-end encryption as a separate design effort. Server-side malware scanning cannot inspect end-to-end encrypted contents.

## Deployment principles

Run Passelio in its own container and dedicated persistent volume. Reverse proxy provides HTTPS. Do not reuse production Erugo data or credentials. Do not replace or modify the existing Erugo deployment while developing Passelio.

Use immutable versioned images; no runtime package updates as a release strategy. Pin dependencies, retain lockfiles, produce release notes and checksums. Capacity and per-share upload limits are configurable, not fixed to the original deployment's disk size.

## Public release checklist

Choose a project license with the owner, add contribution guidelines and private vulnerability reporting, verify naming, document supported versions and limitations, and publish reproducible Docker instructions. The repository remains private until the owner requests publication. Do not claim feature parity or security certification before validation.
