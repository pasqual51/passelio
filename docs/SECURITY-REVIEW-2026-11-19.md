# Internal security review and live S3 retest — 2026-11-19

Reviewed application revision: `6be49078a8be9b60015db1d5dc3fae25ac6e969e` (alpha.11).

This is a developer-performed internal review, **not an independent audit**, penetration test, security certification or guarantee. Independent assessment still requires a separate qualified reviewer and a defined engagement. No production accounts, business data or existing services were changed.

## Completed checks

- `pip-audit 2.10.1 -r requirements.txt`: no known vulnerable dependencies reported at the time of the scan. This covers the pinned Python requirements, not the container operating system or every possible vulnerability.
- Bandit 1.9.4 scanned 2,601 lines across 14 application modules: zero high-severity alerts, five medium and four low. All nine alerts were manually inspected as described below; no exploitable vulnerability was established from these alerts.
- Manual review focused on the flagged SQL construction, session/CSRF authorization, password/MFA reauthentication, OIDC state/nonce/claim validation, registration ownership, email-change confirmation, remote-storage routing and backup handling.
- The existing 77-case regression suite covers the application controls and is rerun for this review. Exact results are available in the execution/CI evidence, rather than being a substitute for independent testing.

## Static-analysis alert disposition

| Alerts | Disposition |
| --- | --- |
| B608: two admin-share SQL queries | Dynamic predicates come exclusively from a fixed allowlist after state validation; search strings, timestamps and offsets use SQL parameters. No request data is concatenated into SQL. |
| B608: database export and full backup | Concatenated table names come exclusively from the literal tuple `oidc_flows`, `oidc_pending`, not from input. |
| B608: lifecycle notification query | Predicates and kinds are selected from a literal, internal list; timestamps and kinds use parameters. |
| B106: two OIDC values | The reported strings are the public Google token endpoint and OAuth authentication method name `client_secret_post`, not embedded credentials. |
| B112: failed object deletion | Failed deletion retains the queued row and lease for a later retry. Exceptions are not returned with credentials or private paths. Operators still need to monitor pending deletion counts. |
| B110: host-key display fallback | Failure to read a stored host key returns an empty display value. This does not bypass Paramiko's pinned-key/RejectPolicy validation. |

## Live S3 integration

The test used a disposable SeaweedFS instance pinned to `sha256:4b42c212543a0acd4c0e675215ecdcaf62a186ef98def76c7e12701871222d15`. Its port was bound to loopback only. A separate temporary Nginx endpoint provided HTTPS using a short-lived test certificate explicitly trusted by the test client; certificate verification remained enabled. Tests traversed an SSH tunnel. All credentials and objects were disposable test data.

The actual Passelio Boto3 adapter passed authenticated bucket access, a 1,048,576-byte single-part transfer and a 9,437,184-byte multipart transfer, downloaded SHA-256 validation and idempotent deletion. Recorded transfer checks took approximately 1.22 and 5.69 seconds respectively; these figures are not a capacity benchmark.

A separate isolated Passelio instance then passed a 9 MiB resumable upload, denial before share-password verification, authenticated download with matching SHA-256, local spool removal, remote-inclusive backup creation/verification, offline restore to local files with matching SHA-256, revocation and deferred remote deletion. The application's temporary S3 prefix was empty after cleanup.

Both test containers (`passelio-s3-integration` and `passelio-s3-tls-integration`), remote certificate/configuration files and temporary SSH tunnels were removed. Existing application containers remained running.

## Remaining limits

- This validates one S3-compatible implementation and the exercised paths, not every S3 provider, IAM deployment or failure mode.
- Actual Google/Microsoft tenant activation still requires operator-owned application credentials; signed-token regression tests are not live tenant approval.
- No independent assessor, production penetration test, container OS scan or long-duration/high-volume stress test was performed in this review.
- Files and secrets are not end-to-end encrypted. Protect data volumes, backup archives, administration access and operator credentials.
