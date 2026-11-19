# Published Docker image review — 2026-11-19

## Alpha.12 baseline

Target: `ghcr.io/pasqual51/passelio@sha256:4776804d3fab9d29abdec5792eb6cea7ef7bee0c2161334aa115d3f760c9b7a6`.
Source revision: `32f59c58b8fece7966548a9fba85ab5dfceeae3f`.
Scanner: Trivy 0.76.2, verified release SHA-256; vulnerability database updated 2026-11-19 01:05 UTC.
Scope: 87 Debian 13.7 packages, 31 Python packages and embedded secrets.

| Severity | Debian package/advisory pairs | Python package/advisory pairs | Total |
| --- | ---: | ---: | ---: |
| Critical | 0 | 0 | 0 |
| High | 48 | 0 | 48 |
| Medium | 104 | 5 | 109 |
| Low | 67 | 1 | 68 |
| Unknown | 10 | 0 | 10 |

The 235 package/advisory pairs represent 108 unique advisory identifiers; the 48 high findings represent 12 unique identifiers. One source-package advisory can match several installed binary packages. No embedded secret was reported. This is not proof of absence of vulnerabilities or exploitable paths.

Available fixes cover eight pairs in two packages:

- `zlib1g`: update `1:1.3.dfsg+really1.3.1-1+b1` to at least `1:1.3.dfsg+really1.3.1-1+deb13u1`, fixing CVE-2026-85091 (high) and CVE-2026-27171 (medium).
- Bundled `pip`: version 25.0.1 has six findings. Version 26.2.0 addresses all six minimum fixed versions; the remediation pins the currently released 26.3.

None of the other pinned application requirements was flagged. The earlier `pip-audit -r requirements.txt` check did not inventory operating-system packages or the base image's bundled pip, explaining the additional findings here.

Most high Debian matches have no fixed version in the current distribution database. Examples concern util-linux privilege/namespace tools, SQLite FTS5/session functionality, ncurses and source-package mappings for systemd libraries. These require reachability and vendor-status review; they must not be silently ignored or treated as proof of remote application compromise. The image runs as UID/GID 10001, but that does not eliminate library vulnerabilities.

Complete normalized findings: [CSV](image-alpha12-2026-11-19.csv). Original JSON, image inspection and database metadata are in the private [scan artifact](https://github.com/pasqual51/passelio/actions/runs/44474975661), retained for 30 days.

## Remediation and release controls

Alpha.13 rebuilds the pinned Python base with all available Debian package upgrades and explicitly uses pip 26.3 to install the application requirements. It then removes pip and ensurepip from the runtime image, including pip's vendored components. The first candidate's scanner gate caught a vendored setuptools inventory finding, so that candidate was not published; removing the unneeded installer addresses this rather than suppressing the scanner. Existing running services are not modified by a source/image rebuild.

Publication now scans the built candidate, keeps all severities and unfixed findings in its artifact, and blocks fixable high/critical OS findings, any fixable Python finding, or embedded secrets. A separate runtime check verifies the patched zlib package, absence of pip/ensurepip, UID 10001, login and checksum-verified upload/download with no network and a read-only root filesystem. These checks must succeed before an image is pushed. Package updates require rebuilding the image; interactive pip installation is intentionally unavailable in the final runtime.

## Validated alpha.13 result

Published image: `ghcr.io/pasqual51/passelio@sha256:18778d1f6cdd6368cb28477952c00cd4057cf9601d681c4d93ddc311b7d50e89`.
Immutable commit tag: `ghcr.io/pasqual51/passelio:sha-f4d99c53349dfe2723aa6b39c1179821171963ee`.
Release tag: `0.1.0-alpha.13`.

The corrected image passes all 77 application tests, dependency/syntax/build checks, the pre-publication vulnerability/secret gate and the isolated non-root/read-only/no-network runtime check. Its publication completed successfully in [GitHub Actions](https://github.com/pasqual51/passelio/actions/runs/44476549705). Full scan evidence is retained in that run's `passelio-candidate-security` artifact for 30 days.

| Result | Alpha.12 | Corrected alpha.13 |
| --- | ---: | ---: |
| Critical matches | 0 | 0 |
| High matches | 48 | 47 |
| Medium matches | 109 | 103 |
| Low matches | 68 | 67 |
| Unknown matches | 10 | 10 |
| Matches with a vendor fix | 8 | 0 |
| Python vulnerability matches | 6 | 0 |
| Embedded secrets reported | 0 | 0 |

All eight fixable baseline pairs disappeared, with no new package/advisory pair introduced in the final candidate. The remaining 227 pairs represent 100 unique advisory IDs and have no fixed version in the scanner's current Debian data. Of these, 47 are high matches (11 unique IDs). They remain visible and require ongoing vendor/reachability review; this is **not a zero-vulnerability image**. Corrected complete findings: [CSV](image-alpha13-2026-11-19.csv).

The patch was applied to the image build and a new image was published. Existing running services were not restarted or silently redeployed. Deployments using alpha.12 or earlier must switch to the corrected digest/tag using the documented upgrade and backup procedure.

Sources: [Debian zlib advisory](https://security-tracker.debian.org/tracker/CVE-2026-85091), [Debian util-linux status example](https://security-tracker.debian.org/tracker/CVE-2026-78408), [PyPA pip advisory](https://github.com/pypa/advisory-database/blob/main/vulns/pip/PYSEC-2026-3721.yaml), [Trivy immutable release](https://github.com/aquasecurity/trivy/releases/tag/v0.76.2).
