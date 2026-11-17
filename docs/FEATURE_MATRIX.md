# Functional reference and implementation tracker

The owner supplied reference screenshots of a self-hosted sharing application on 17 November 2026. They describe desired capabilities, not an instruction to copy branding, third-party assets, corporate data or source code. Passelio retains its own identity and implementation. No screenshots, personal account lists or company assets are published in this repository.

| Area | Implemented in Passelio | Remaining work |
| --- | --- | --- |
| About | Version exposed in instance status and health; project documentation | Dedicated about page, dependency/runtime information and verified support/license links |
| Statistics | Users, active shares, files, logical storage, physical free space, cleanup backlog | Time-range charts, protected/expired counts, top shares and user activity summaries |
| Visual identity | Original design; name/logo/favicon/backgrounds; validated raster imports; image rotation; logo width; 17 presets and safe color-only JSON import/export | Optional video support and advanced theme palettes |
| General system settings | Application name, share/email base URL, login message and default language with explanatory help | Optional visibility of language selector and additional display preferences |
| Sharing settings | Default/max expiry, global/per-share quotas, default download limit, optional mandatory share password | Reverse/upload requests, configurable retention after expiry, human-readable link modes, resumable uploads and folders/ZIP |
| Notifications | Explicit bilingual share notifications, automatic CC/BCC, persistent delivery history and retry | Download, soon-to-expire, expired and cleanup lifecycle notifications with idempotent scheduling |
| SMTP | Host, port, STARTTLS/SSL, username, password keep/remove behavior, sender, explicit test and safe diagnostics | Provider-specific integrations and bounce processing |
| Authentication | Administrator-created users, password hashing, CSRF, rate limiting, sessions and configurable session lifetime | Verified self-registration, domain restrictions, OAuth/OIDC provider management, MFA and account recovery |
| Database backups | Administrator-only consistent downloadable SQLite snapshot, rate and size limits, audit record | Scheduled retained server backups, backup listing/retention and validated restoration workflow |
| Email templates | Editable plain-text subject/body in French and English for share notifications | Dedicated template workspace, base layout, headings/action buttons, account/reset/upload-request/lifecycle templates and previews |
| Users | Creation, search, admin/user roles, disable/re-enable, session invalidation and protected administrator safeguards | Display names/profile metadata, invitation/reset flow, per-user share filter and controlled permanent deletion |
| All shares | Owner/title search, size/state/download counts, expiry and administrator revocation | Pagination/filter controls, details view and retained/deleted state management |
| My shares | Create, list, notify, copy link and revoke | Details/actions, expiry extension and filters |
| Profile | Password change and saved language preference | Editable display name/email with verification and linked identities |

## Delivery order

1. Finish and validate grouped system settings with field-level help; keep all existing administration features working.
2. Visual customization delivered in alpha.5; add a dedicated email-template workspace next.
3. Add account invitation/recovery and richer profile/user management.
4. Add upload requests and reliable resumable transfers.
5. Add lifecycle notifications, retention and expanded statistics, then review advanced identity providers and backup automation.

Each area requires backend enforcement, bilingual labels, authorization tests, persistence checks and browser validation before being described as complete. Unsupported features must not be represented by working-looking controls.
