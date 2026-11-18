# Security status

Passelio is an early private alpha. It has not received an independent security audit. Do not use it for regulated, confidential or production data yet.

Current controls include scrypt password hashing, random share tokens, hashed server-side session tokens, same-site HTTP-only cookies, CSRF checks, security headers, download-as-attachment, opaque storage paths and transactional quota reservation. These are implementation controls, not a certification or guarantee.

SMTP credentials are stored in a mode-600 application-owned file, not returned by the API or included in error messages. This is not encryption at rest: protect the data volume and backups. TLS server verification is mandatory; plain SMTP is restricted to an explicit development-only environment option. Automatic CC/BCC recipients receive share links, so configure them deliberately and inform users. Outbox records contain recipient metadata; establish retention before production.

Branding imports are administrator-only and re-encode bounded raster inputs without metadata. Uploaded SVG/HTML/video/animation is not accepted. Visual assets are intentionally public by identifier and require a full-volume backup. Themes accept only validated colors, not CSS or code. These controls reduce attack surface but do not replace dependency maintenance or independent review.

Require HTTPS outside local development, preserve certificate validation, protect backup volumes and bootstrap secrets, and restrict access to the test deployment. Anyone possessing an unprotected share link can access that share. A password-protected share requires both the link and its password; this is not end-to-end encryption.

Known limitations are documented in README.md and docs/DEPLOYMENT.md. Security fixes must be built into a versioned image, not installed interactively into a running container. CI does not replace a security review.

Contact the repository owner privately for security issues. Do not include passwords, private keys, real files or active share/session tokens in public issues. A formal supported-version policy and private reporting channel must be established before public release.

Optional TOTP MFA requires password reauthentication and a valid first code to enable. Successful TOTP counters and hashed recovery-code consumption are committed atomically with login session creation, preventing concurrent reuse. Password recovery does not remove MFA. Authenticator seeds are stored separately in private mode-600 files (not encrypted at rest); full backups include them. Enabling or disabling MFA invalidates sessions. No web administrator bypass is provided. Keep recovery codes offline and retain a controlled operator recovery procedure.

Retained backup archives include account information, active authenticator secrets, completed files and SMTP credentials. They are confidential, unencrypted archives, accessible only to administrators. Automatic scheduling is opt-in; a separate Docker volume is not off-site protection. Restore is deliberately offline into a new directory and disables restored schedules. After restoring an old backup, review factor enrollment and recovery-code state. Hard-linked staging files keep completed blobs available during backup without holding the database writer lock for the entire ZIP transfer.
