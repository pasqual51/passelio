# File storage: local, S3 and SFTP

Local disk remains the default. The administration interface selects and configures the destination for new files; an operator-mounted JSON remains an optional initial configuration. Each file records its destination; switching the default does not move existing data. Multiple configured destinations may coexist. Do not remove or change a destination while it contains application files or queued object deletions: startup rejects that change. This release does not provide automatic migration between destinations.

## Configure from the interface (alpha.10)

Open Administration → Storage. The default selector chooses the destination of new uploads. Unconfigured remote destinations remain disabled until their settings are saved. Open Configure S3 or Configure SFTP, enter the required fields, confirm your current password and add an unused authenticator/recovery code if MFA is enabled. Test and save settings performs a read-only connection check before committing; it does not create a remote file or prove write permission. The optional checkbox makes that destination the default immediately. A failed check leaves the prior settings unchanged.

S3 fields include HTTPS endpoint (blank for AWS), region, bucket, prefix, addressing style, role authentication or access-key credentials, and an optional temporary session token. SFTP fields include host, port, username, absolute directory as seen by the SFTP account, verified server public SSH key, and password or private-key/passphrase authentication. Obtain the server public key through a trusted channel; Passelio does not fetch-and-trust unknown keys. The directory must exist beforehand. Original filenames are never remote paths.

Leave saved secret fields blank to retain their values. The interface only returns presence flags, not passwords, keys or passphrases. A new private key requires its own passphrase if encrypted; an old passphrase is not silently applied to a replacement key. Explicit checkboxes remove a saved temporary S3 token or saved passphrase (the latter requires a usable unencrypted key). A destination with files, queued deletion or active backup pins cannot change its identity (server/account/directory or endpoint/region/bucket/prefix); valid credentials may be rotated for the same identity. Existing files are never migrated by changing the default.

Settings are revisioned in SQLite, while credentials are in private generation directories under DATA_DIR/storage-secrets, mode 700 for directories and 600 for files. They are not encrypted at rest: protect DATA_DIR and use HTTPS for administration outside local development. Unreferenced old secret generations are removed after seven days; an in-use generation is retained. Web processes check revisions before each request and the worker refreshes each cycle, so no Docker restart is required for interface changes. Stale concurrent edits are rejected, and old process snapshots cannot reserve or read files against a replaced destination binding.

Interface settings take precedence over operator-mounted settings. A mounted initial configuration can be viewed and edited from the interface; saving that provider copies its retained credentials into application-managed files. A default-only change retains any existing mounted credential references, so those mounts must stay available until the providers are resaved. Never remove mounts still referenced by active settings.

## Optional operator-mounted initial configuration

1. Copy either storage.s3.example.json or storage.sftp.example.json into secrets/storage/config.json and replace the example values. You may include both the s3 and sftp sections and choose one default: local, s3 or sftp.
2. Place referenced credential and trust files in secrets/storage. On Linux, use a directory owned by container UID 10001 with mode 700 and credential files owned by that UID with mode 600. On Windows, protect the folder with ACLs and verify that the container user can read it. Never commit these files.
3. Start both processes with the override:

```sh
docker compose -f compose.yml -f compose.storage.example.yml up -d --build
```

For non-Compose deployments, set STORAGE_CONFIG_FILE to the JSON file path and mount it and its referenced files read-only into both app and worker. Advanced mounted credentials are not returned through the storage administration API. Interface-managed credentials are entered over the administration connection and saved in private application files. The page Administration → Storage configures destinations and shows the default, file counts and queued remote deletions. Its connection test is read-only; it does not prove upload/delete permissions.

Do not point another installation at the same managed namespace unless you understand the lifecycle implications. Keep separate buckets/prefixes or SFTP account roots for independent installations. Database-only exports are not complete remote-data backups.

## S3 compatible

Use a private bucket and HTTPS. Do not enable anonymous bucket/object access. The SDK verifies TLS certificates; use AWS_CA_BUNDLE with a mounted CA bundle for a private certificate authority instead of disabling validation. The endpoint must be an HTTPS origin without embedded credentials or query parameters. Omit endpoint_url for standard AWS S3; set the provider endpoint and region for Scaleway or an HTTPS MinIO deployment. Addressing style can be auto, path or virtual.

Required object operations include PutObject, GetObject and DeleteObject, plus multipart upload/abort operations for large files. The read-only connection check uses HeadBucket, which may require bucket-level ListBucket permission. An access key and secret are read from files. Optional session_token_file supports temporary credentials. For deployments using an explicitly configured instance/workload role, use use_iam_role: true instead of key-file fields. Follow the provider's least-privilege policy and key-rotation instructions.

Objects use opaque identifiers under the configured prefix; original filenames are not object keys. Uploads use the official Boto3 transfer manager, bounded 8 MiB multipart buffers and no public ACL. The application checks object length and retains the source SHA-256 in its database/metadata. Bucket versioning and lifecycle rules remain the operator's responsibility. DeleteObject on a versioned bucket normally creates a delete marker rather than purging historical versions; configure noncurrent-version retention separately. Configure cleanup of abandoned multipart uploads as well. S3-compatible does not mean every vendor/version has been tested: CI exercises the AWS SDK with stubbed operations; validate your chosen endpoint before production.

## SFTP / SFTPGo

Create a dedicated SFTP account restricted to a private directory, with read, write, rename, stat and delete permissions. For SFTPGo, root is the absolute path **as seen by that SFTP account**, for example /passelio inside its virtual home, not an operating-system path such as /data on the host. Create the directory before configuring Passelio. Do not reuse the website backup account or its directory.

The server key must already be present in known_hosts and must be verified through a trusted channel, such as the server console or administrator-provided fingerprint. An unverified ssh-keyscan result alone is not proof of identity. Nonstandard ports use OpenSSH's [hostname]:port known_hosts syntax. Unknown and changed host keys are rejected; there is no automatic trust option.

Authenticate using private_key_file, optionally passphrase_file for an encrypted key, or password_file for password authentication. Keys, passwords and passphrases stay in mounted private files. SSH agent forwarding, local key discovery, shell commands and remote command execution are not used. The configured host can be private/VPN reachable; use your own network restrictions.

Each upload uses a fresh opaque identifier and an exclusive .part file with mode 600, then a standard rename to publish the complete object. The server must support those operations. Remote paths never contain user-provided file names. CI includes a real loopback SFTP server with host-key verification and protocol upload/read/rename/delete tests; SFTPGo is supported through the SFTP protocol, but a live SFTPGo deployment has not been changed by this implementation.

## Uploads, cleanup and failures

Uploads first use temporary local spool space, including with remote storage. Quotas reserve the entire logical file size before accepting bytes. Finalization hashes and sends the completed spool outside the database writer lock; a per-upload lease prevents simultaneous completion/cancellation. A crashed finalizer can require waiting up to one hour before retrying. A completed response lost in transit is recognized by upload status, avoiding a duplicate file on retry. Successful remote files release their local spool; cleanup retries leftover spools.

Remote failures return a generic storage-unavailable error, never server paths or credentials. Resumable uploads keep their completed local spool for retry. Revoked/expired or abandoned files queue remote deletion; the worker retries outside HTTP requests. Deletions wait at least one minute, are leased and are deferred while an object is still referenced or pinned by a backup. Logical quota is released before the remote cleanup completes; monitor queued deletions, remote capacity and provider billing. Pending spools expire after 24 hours without upload activity. Interrupted multipart/SFTP partial files may also need provider-side or operator cleanup after a hard crash.

All downloads pass through Passelio authorization/password/expiry/download-limit checks. No public bucket URL, SFTP credential or provider-presigned link is returned. ZIP downloads still need temporary local disk space and can be slower for large remote collections. Uploads, remote streams and backups depend on network availability. Remote storage is not end-to-end encryption.

## Full backup and restore

Full backups include remote file bytes, not just remote object names. Active remote objects are pinned while the snapshot is copied, and the backup validates their size and SHA-256. Pins from a crashed backup expire after 24 hours. Run the CLI with the same STORAGE_CONFIG_FILE and credential mounts as the application, or use the administration worker.

The archive normalizes file records to local storage and excludes remote deletion queues, bindings, active pins and saved interface storage settings/credentials. Offline restore therefore produces a self-contained local data directory and does not delete anything in the original remote destination. Reconfigure remote storage explicitly afterward for new files if desired. Backups require enough free space for the complete archive even when the live files are remote. Archives include private application secrets and are not encrypted by Passelio; keep independent encrypted backups.
