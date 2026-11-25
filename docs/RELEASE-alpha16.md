# 0.1.0-alpha.16

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
