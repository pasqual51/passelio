# Functional reference and implementation tracker

The owner supplied reference screenshots of a self-hosted sharing application on 17 November 2026. They describe desired capabilities, not an instruction to copy branding, third-party assets, corporate data or source code. Passelio retains its own identity and implementation. No screenshots, personal account lists or company assets are published in this repository.

| Area | Implemented in Passelio | Remaining work |
| --- | --- | --- |
| About | Version exposed in instance status and health; project documentation | Dedicated about page, dependency/runtime information and verified support/license links |
| Statistics | Users, active shares, files, logical storage, physical free space, cleanup backlog | Per-day download chart (7/30/90 days), state counts API, top shares and activity summaries delivered; richer filters remain |
| Visual identity | Original design; name/logo/favicon/backgrounds; validated raster imports; image rotation; logo width; 17 presets and safe color-only JSON import/export | Optional video support and advanced theme palettes |
| General system settings | Application name, share/email base URL, login message and default language with explanatory help | Optional visibility of language selector and additional display preferences |
| Sharing settings | Default/max expiry, global/per-share quotas, default download limit, optional mandatory share password | Upload-only requests, quota-reserved resumable uploads, folders and ZIP delivered; configurable retention and human-readable link modes remain |
| Notifications | Explicit bilingual share notifications, automatic CC/BCC, persistent delivery history and retry | First-download, soon-to-expire, expired and revoked notifications delivered (opt-in, idempotent scheduling); cleanup notices remain |
| SMTP | Host, port, STARTTLS/SSL, username, password keep/remove behavior, sender, explicit test and safe diagnostics | Provider-specific integrations and bounce processing |
| Authentication | Administrator-created users, password hashing, CSRF, rate limiting, sessions and configurable session lifetime | Invitation/recovery via single-use links delivered; verified self-registration, domain restrictions, OAuth/OIDC remains; optional TOTP MFA delivered in alpha.8 |
| Database backups | Administrator-only consistent downloadable SQLite snapshot, rate and size limits, audit record | Consistent full backup/verify/offline restore CLI delivered; daily/weekly scheduling, retention and management UI delivered in alpha.8 |
| Email templates | Editable plain-text subject/body in French and English for share notifications | Plain-text invitation/reset/lifecycle workspace and example preview delivered; HTML layout/button editor and upload-request emails remain |
| Users | Creation, search, admin/user roles, disable/re-enable, session invalidation and protected administrator safeguards | Display names and invitation/reset flow delivered; email verification/change, per-user share filter and controlled deletion remain |
| All shares | Owner/title search, size/state/download counts, expiry and administrator revocation | Pagination/filter controls, details view and retained/deleted state management |
| My shares | Create, list, notify, copy link and revoke | Details/actions, expiry extension and filters |
| Profile | Password change and saved language preference | Editable display name delivered; verified email change and linked identities remain |

## Delivery order

1. Finish and validate grouped system settings with field-level help; keep all existing administration features working.
2. Visual customization delivered in alpha.5; add a dedicated email-template workspace next.
3. Add account invitation/recovery and richer profile/user management.
4. Add upload requests and reliable resumable transfers.
5. Add lifecycle notifications, retention and expanded statistics, then review advanced identity providers and backup automation.

Each area requires backend enforcement, bilingual labels, authorization tests, persistence checks and browser validation before being described as complete. Unsupported features must not be represented by working-looking controls.

## Alpha.7 integration status (18 November 2026)

Delivered: account invitations/recovery/profile names, opt-in lifecycle email and templates, statistics, folder/ZIP transfer, upload-only requests, resumable uploads and full backup/restore CLI. New APIs and UI are loaded together by a running process: static edits become visible only after restart, preventing frontend/backend mismatch.

Not yet implemented: OIDC (Microsoft/Google), S3, verified self-registration/email change and production release. AGPL v3 has been recommended to the owner; no license choice or publication is implied by that recommendation. Do not represent this alpha as feature-complete or ready for public production.

## Alpha.8 security and backup automation (18 November 2026)

Optional TOTP enrollment requires password reauthentication and a valid authenticator code. Authentication is replay-protected atomically across concurrent workers, with ten hashed single-use recovery codes and session revocation on enable/disable. Email password recovery does not bypass MFA. Secrets are separate private files and are included only in full backups, not database exports. Account email change, SSO and self-registration remain pending.

Full backups can now be queued from administration or scheduled daily/weekly, with 1–14 retained verified archives, safe failure status and authenticated downloads. The worker creates archives; automated backups default to disabled. Restore stays offline into a new directory and resets the schedule. Backups are not encrypted and must be copied to independent protected storage for disaster recovery.
