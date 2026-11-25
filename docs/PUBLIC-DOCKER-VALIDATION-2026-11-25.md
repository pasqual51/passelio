# Public Docker installation validation — 2026-11-25

Image: `ghcr.io/pasqual51/passelio:0.1.0-alpha.16`

Validated digest:
`sha256:b5f682f3cb375cd254b88715c2b20dac27d84577ed65318ef0026ac61d0df2f0`

Source revision: `260c4cbd2ee231f6996d76c45839ba2c4ff7300f`.
The [publication workflow](https://github.com/pasqual51/passelio/actions/runs/45610507495)
completed its application tests, JavaScript checks, dependency audit, image build,
candidate vulnerability/secret scan and isolated runtime checks before pushing.
The package is public and connected to the public source repository. That
repository's Actions have package write access.

## Anonymous registry access

The version tag and the previously pinned alpha.16 digest were pulled using an
isolated Docker configuration containing only `{"auths":{}}`. Registry override
environment variables were removed. No user account, `docker login`, personal
access token or stored credential helper was supplied. An independent anonymous
registry manifest request returned HTTP 200 and the validated digest above.
Normal Docker registry protocol may issue an anonymous bearer token internally.
Existing image-layer caches were not deleted.

## Fresh installation

Two isolated installations were exercised on Linux/amd64: a direct container
installation and the published `compose.image.yml` using new project-scoped named
volumes. The Compose test used the official Compose v5.8.0 standalone binary,
verified against its published SHA-256, because the test host did not have the
Compose plugin installed. Only the test host port was changed to another loopback
port; no application source was mounted into the containers.

Both the web application and background worker started with a synthetic
administrator and a randomly generated disposable password. Checks passed for:

- HTTP health and expected application version;
- refusal of anonymous access to private shares;
- administrator login on the initially empty database;
- share creation and file upload through the real HTTP server;
- downloaded content matching the original SHA-256;
- administrator login and the same file content after both services restarted.

Containers ran with a read-only root filesystem, without root privileges or Linux
capabilities. Only disposable test data/backups and the synthetic administrator
secret were mounted. The host port was bound to loopback.

All test containers, networks, named volumes, synthetic secrets and the temporary
Compose executable were removed after validation. Existing installations and
their data were not used by these tests.

This validates the tested public installation path. It does not establish ARM
compatibility, complete production readiness or an independent security audit.
See the security review documents for the remaining advisory assessments.
