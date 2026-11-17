# Security status

Passelio is an early private alpha. It has not received an independent security audit. Do not use it for regulated, confidential or production data yet.

Current controls include scrypt password hashing, random share tokens, hashed server-side session tokens, same-site HTTP-only cookies, CSRF checks, security headers, download-as-attachment, opaque storage paths and transactional quota reservation. These are implementation controls, not a certification or guarantee.

Require HTTPS outside local development, preserve certificate validation, protect backup volumes and bootstrap secrets, and restrict access to the test deployment. Anyone possessing an unprotected share link can access that share. A password-protected share requires both the link and its password; this is not end-to-end encryption.

Known limitations are documented in README.md and docs/DEPLOYMENT.md. Security fixes must be built into a versioned image, not installed interactively into a running container. CI does not replace a security review.

Contact the repository owner privately for security issues. Do not include passwords, private keys, real files or active share/session tokens in public issues. A formal supported-version policy and private reporting channel must be established before public release.
