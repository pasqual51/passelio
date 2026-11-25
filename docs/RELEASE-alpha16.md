# 0.1.0-alpha.16

## First public alpha / Première alpha publique

Passelio is available for early Docker and Unraid testing under AGPL-3.0-only.
The container image is public and can be downloaded without a GitHub account or
personal access token. Use `compose.image.yml` for a prebuilt-image installation;
the Unraid templates pin a validated image digest.

The application includes an English/French interface, expiring/password-protected
shares, resumable authenticated uploads, upload requests, email notifications,
user administration and quotas, TOTP, local/S3-compatible/SFTP storage, custom
branding and application backup/restore.

Public screenshots use a separate demonstration with fictional data. The interface
now consistently identifies the release as a public alpha in both languages.

This is not production-ready software. An independent security audit has not been
completed. Antivirus scanning, webhooks and end-to-end encryption are not available.
Use test data and read [SECURITY.md](../SECURITY.md) before evaluation.

Pour les premiers essais : [installation en français](README.fr.md),
[installation Unraid](UNRAID.fr.md) et [captures de démonstration](../README.md#screenshots).
Les annonces communautaires sont préparées en [français](ANNOUNCEMENT.fr.txt)
et en [anglais](ANNOUNCEMENT.en.txt).

## Authenticator enrollment

Authenticator setup now displays a locally generated QR code in French and English.
The PNG encodes the existing standard otpauth URI, including issuer, account label,
SHA-1, six digits and a 30-second period. No third-party QR service receives the seed.
Manual secret entry remains available. Enrollment images and seeds are cleared
on expiry, successful activation and sign-out. Responses retain no-store caching.

The QR generator is pinned to qrcode 8.2. A test-only independent decoder,
zxing-cpp 3.2.0, verifies the generated PNG against the provisioning URI and secret.
The decoder is not installed in the production image.

Existing accounts and enabled factors do not change. For an unfinished setup,
reload the page and start enrollment again to display the QR code. Scan it in your
authenticator, enter its current code and privately retain the recovery codes.
