# Review of the eleven remaining high advisory IDs — 2026-11-19

Scope: alpha.13's 47 high package/advisory matches, representing eleven advisory IDs. Debian tracker pages and the application code were reviewed. Conclusions below concern the current application paths and default non-root deployment; they are not a penetration test or a claim that retained libraries are patched. Raw scanner findings remain enabled, including unfixed advisories.

## Package reduction in alpha.14

The image build removes exactly seven unneeded packages after updates, dependency installation and creation of UID/GID 10001: `apt`, `libapt-pkg7.0`, `mount`, `login`, `libncursesw6`, `adduser`, `passwd`. No automatic removal of other dependencies is performed: Python links native libraries outside Debian's package dependency graph, so broad autoremove would be unsafe.

`login` is protected for a general-purpose Debian system. This dedicated application image provides neither interactive login nor PAM authentication; the operating-system account is created before pruning and verified afterwards. The removal script explicitly validates the simulated removal set, rejects any Essential package and any unexpected installation/removal, preserves all originally installed Essential packages, and requires a clean `dpkg --audit`. The allow flag is confined to that checked, disposable image build. It does not operate on the Docker host or existing services.

An isolated dry run and actual package-removal trial passed; Python SQLite, TLS, ctypes, compression and readline imports remained functional. CI additionally checks the final application container, its retained CA trust store/native modules, PNG processing, login, checksum-verified transfers and full backup/restore with no network, no capabilities and a read-only root filesystem.

## Per-advisory assessment

| Advisory | Affected feature / precondition | Current application exposure and decision |
| --- | --- | --- |
| [CVE-2026-76642](https://security-tracker.debian.org/tracker/CVE-2026-76642) | Privileged mount helpers and post-mount hooks | Remove the `mount` executable package. Retain util-linux libraries required by Essential packages. Passelio does not mount filesystems or call libmount; the default process has no mount capability. Retained source-package matches are not a vendor patch. |
| [CVE-2026-78408](https://security-tracker.debian.org/tracker/CVE-2026-78408) | Privileged `nsenter --join-cgroup` invocation | `nsenter` belongs to retained util-linux. There is no application subprocess path invoking it. UID 10001, dropped capabilities and no-new-privileges reduce the privileged preconditions. Do not expose an operator shell or run privileged containers. |
| [CVE-2026-78409](https://security-tracker.debian.org/tracker/CVE-2026-78409) | fstab-authorized `X-mount.subdir` and namespace/path manipulation | Remove `mount`; no fstab/mount feature or filesystem-namespace API is offered to application users. Libraries remain for the distribution's dependency consistency. |
| [CVE-2026-78410](https://security-tracker.debian.org/tracker/CVE-2026-78410) | Privileged restricted bind mounting with attacker-writable source ancestors | Remove `mount`; Passelio has no bind-mount endpoint. Normal Docker volume setup is performed by the host runtime, not by this image's mount executable. Retained matches remain visible. |
| [CVE-2026-16742](https://security-tracker.debian.org/tracker/CVE-2026-16742) | The `systemd-homed` service and managed local users | The affected daemon is not present or started. The image retains only distribution libraries needed by Essential packages, producing source-package scanner matches. Final-container inventory verifies daemon absence; reassess if adding system services. |
| [CVE-2026-54369](https://security-tracker.debian.org/tracker/CVE-2026-54369) | A privileged caller of pathname-based libacl functions with attacker-controlled symlinks | libacl is required by Essential coreutils/sed/tar. The application does not call ACL APIs or invoke these utilities against upload paths. Runtime file operations use Python under UID 10001 and opaque server-generated storage names. Keep the library and monitor Debian; non-root is a mitigation, not a library fix. |
| [CVE-2025-69720](https://security-tracker.debian.org/tracker/CVE-2025-69720) | The `infocmp` terminal-description CLI | Remove unneeded `libncursesw6`; retain libtinfo/readline and Essential ncurses packages. `infocmp` remains part of Essential ncurses-bin but is not called by Passelio or exposed through HTTP. Removing all ncurses packages would break dependency consistency. |
| [CVE-2026-9538](https://security-tracker.debian.org/tracker/CVE-2026-9538) | Perl `Archive::Tar` parsing of crafted headers | Only minimal perl-base is retained for Essential distribution tools. `perl -MArchive::Tar` confirms the affected module is not installed. Passelio backups use Python zipfile and never invoke Perl. Keep the raw source-package match; do not install additional Perl archive modules without reassessment. |
| [CVE-2026-119373](https://security-tracker.debian.org/tracker/CVE-2026-119373) | FTS5 detail=none prefix MATCH queries and attacker-controlled rowids | SQLite is required for application data. Passelio creates normal tables only, uses parameterized SQL, offers no arbitrary-SQL endpoint and has no FTS5/MATCH feature. Uploaded files are not opened as databases. The compiled library remains affected; keep the finding and monitor the vendor. |
| [CVE-2026-119374](https://security-tracker.debian.org/tracker/CVE-2026-119374) | A corrupted FTS5 index deleted with secure-delete enabled | The application schema contains no FTS5 table/index. The distribution library has SECURE_DELETE compiled in, so disabling secure-delete is not claimed as a mitigation. Offline database restore is an operator trust boundary: accept only verified backups from trusted origins. Do not infer that opening arbitrary attacker-supplied databases is safe. |
| [CVE-2026-119379](https://security-tracker.debian.org/tracker/CVE-2026-119379) | Crafted session changesets passed to sqlite3changeset_apply | The SQLite session changeset API is not used or exposed by Passelio's Python database layer. The library is retained and inventoried; adding replication/change-set import would invalidate this assessment. |

## Boundaries and follow-up

The default Compose configuration runs UID 10001, drops all capabilities, enables no-new-privileges and mounts the root filesystem read-only. An operator who overrides those controls changes this assessment. These conclusions do not cover a compromised host, a privileged container or arbitrary code execution by an administrator.

No Debian experimental/unstable packages, custom replacement native libraries or scanner ignore rules were introduced. Packages still required by the supported distribution and application are retained. Eliminating duplicate package matches is not the same as patching all eleven advisory IDs.


## Validated alpha.14 result

Published digest: `ghcr.io/pasqual51/passelio@sha256:cbfae5c9266051f1b68a63c1de1144f7722b1803a84ad0976804d4fdf207c05d`.
Immutable source tag: `ghcr.io/pasqual51/passelio:sha-7b30ff732f4f6a002dccd45ec4b4148f9f443e82`.
[Successful build, scan, runtime verification and publication](https://github.com/pasqual51/passelio/actions/runs/44479152264); full evidence is in its `passelio-candidate-security` artifact (30-day retention).

| Measurement | Alpha.13 | Alpha.14 |
| --- | ---: | ---: |
| Debian packages | 87 | 80 |
| High matches | 47 | 38 |
| Medium matches | 103 | 101 |
| Low matches | 67 | 59 |
| Unknown matches | 10 | 10 |
| Total package/advisory matches | 227 | 208 |
| Unique advisory IDs | 100 | 99 |
| Unique high advisory IDs | 11 | 11 |
| Critical matches / fixable matches / Python findings / secrets | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |

Nineteen package/advisory pairs disappeared, including nine high matches, and no new pair was introduced. Complete unsuppressed findings: [CSV](image-alpha14-2026-11-19.csv).

All 82 regression cases passed, including five removal-plan safety cases. The final container preserved UID 10001 and all Essential packages, passed `dpkg --audit`, and verified TLS CA trust, Python native module imports, login, SHA-256 upload/download, full backup/restore and PNG processing with no network/capabilities and a read-only root filesystem. The runtime inventory confirms `mount`, `umount`, `login`, `useradd`, apt and pip are absent; `infocmp` and `nsenter` remain in retained Essential packages. `systemd-homed`, `setfacl` and Perl `Archive::Tar` are absent. SQLite 3.46.1 retains compiled FTS5 and session support; the application schema does not use those features.

The remaining 38 high matches have no fixed version in the scanner's current Debian data. They are retained for vendor/reachability review, not waived as fixed. This remains an internally reviewed application image, not an independently certified or zero-vulnerability release. Existing running services were not redeployed by these image-build changes.
