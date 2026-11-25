# Private Unraid validation — 25 November 2026

Runtime: alpha.15, source `a82968ef774e0d716fcfe850d46c73772f5d66f2`, image
`ghcr.io/pasqual51/passelio@sha256:a20c6244196a4332774c6fca6b886bb565ffd9be496fcab34c58f53600598526`.
This is developer validation, not an independent security audit or a public-release approval.

## Completed

- CI: 84 tests, JavaScript syntax, dependency audit, Docker construction, full image scan and hardened runtime checks. Six independent initializers against fresh/existing volumes are covered. On Unraid, three series of six concurrent initializers passed with database integrity and one administrator.
- Browser: file and nested-folder upload, ZIP download, accented filenames and byte/SHA-256 equality. HTTP checks verified password gates, wrong-password rejection, revocation, expiry and download limits. Expiry was induced only on an identified disposable share; the server clock was not changed.
- Real SMTP: a French share notification reached the owner's Gmail inbox. The received link opened the private trial and downloaded the expected file with matching SHA-256. Delivery is private-Tailscale-only because the application URL is private. No external production recipient was used.
- Real local/S3/SFTP: isolated services on an internal Docker network with no host ports. SeaweedFS S3 was accessed through a certificate-verified HTTPS proxy and OpenSSH SFTP through an independently retrieved, pinned host key. A substituted host key was rejected.
- For each backend, GUI configuration API, persisted reload, resumable 1 MiB and 9 MiB uploads, SHA-256 download, spool removal for remote objects, three worker backup cycles with retention of two, archive verification, restoration to local files and remote deletion were verified. The S3 9 MiB object exercises multipart upload. The custom test proxy was corrected to preserve HEAD content length and support chunked transfers before the successful run.
- TOTP on a synthetic account: enrollment, password-only rejection, real-clock TOTP login, replay rejection, single-use recovery, full-backup restoration and authenticated disabling passed. The owner's account was not enrolled automatically; pairing an authenticator and retaining recovery codes require the owner.
- Live instance: daily full backups enabled, seven archives retained. The first worker-produced archive was verified and restored without network in a new directory. Restored application boot, administrator presence, a shared-file download SHA-256 and SMTP-secret presence passed. Restored sessions were empty and automatic scheduling was disabled, as designed. The live volume was not replaced.
- Temporary service containers and Docker network were removed. Synthetic datasets and disposable credentials were removed; result metadata and image identities were retained privately.

## Scope and limits

Small fixtures do not establish 2 GiB performance, sustained-load, proxy/public-HTTPS, WAN interruption or arbitrary provider compatibility. S3/SFTP remain optional; the owner's default storage remains local. Test services are not permanent storage destinations. Backups on the same pool are not an off-server disaster-recovery copy.

The alpha.15 image scan retained 44 high package/advisory matches across 13 CVE IDs, with no fixed version reported by that scan. It found no critical, Python-package or embedded-secret findings. All severities remain in the original scan artifact. The absence of a known package fix or a CI publication blocker does not establish non-exploitability. Independent review and later scanner updates remain required before a public release.

## Repeating the disposable storage checks

`scripts/integration_unraid.py` runs inside the exact application image, with `/qa` mapped to a fresh private scratch directory owned by UID/GID 10001. Do not mount production data. Provide synthetic `credentials.json` (`access`, `secret`, `sftp`), `admin_password`, and the OpenSSH container's host public key as `sftp.pub`.

On an internal Docker network, start the official SeaweedFS image as `passelio-qa-s3` with a pre-created `passelio-qa` bucket and matching synthetic credentials, and the official atmoz/OpenSSH image as `passelio-qa-sftp` with user `qa` and writable `/objects`. Publish no ports and grant no host/Docker socket mounts. Run the script in a non-root application container on that network. It creates a new per-run scratch subdirectory, prints explicit pass markers and writes results JSON. Stop/remove the services and network and remove synthetic credentials after the run. Preserve the exact service-image digests with the results.

Reference service setup: [SeaweedFS mini](https://github.com/seaweedfs/seaweedfs/wiki/Quick-Start-with-weed-mini), [atmoz SFTP](https://github.com/atmoz/sftp).
