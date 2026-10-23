# Validation scope

This is the first public version. Treat it as an operator toolkit with an explicit validation boundary.

## Automated checks

The unit suite covers patch direction and idempotency, failed preparation cleanup, source preservation, symlink/traversal rejection, cached archive tampering, report permissions, root/build-OS guards, Debian/Remi runtime names, stale mapped-module device/inode detection, package hardlinks, installed-file tampering, and CLI error codes. A live Linux test compiles an owned PHP-named fixture, loads a shared library, and checks real `/proc` detection after replacing its mapped library and executable.

The Ubuntu 18.04 container also creates and reads an actual Debian binary package. That one format-specific unit test is skipped on CentOS, where dpkg is absent. Both native container jobs exercise the actual native format separately.

Each native job does the following:

1. Run the unit suite on the distribution's Python 3.6 under `LC_ALL=C`, including UTF-8 packaging text and subprocess output.
2. Prepare a synthetic source package with an owned C fixture and test patch.
3. Run the CLI's native build command as an unprivileged user.
4. Check that the compiled fixture executes its patched behavior.
5. Generate a manifest from the exact `.deb` or RPM payloads.
6. Verify staged payloads and detect a modified file.
7. Run inventory and require an incomplete process audit when no PHP process exists.
8. Install the fixture inside the disposable container, compare real installed package versions/files, and reject deliberate tampering.

The smoke patch is original test code. It does not contain PHP source and does not substitute for testing the real security backports.

## Additional checks during initial development

All six pinned publisher archives were downloaded over HTTPS and checked against catalog SHA256 values. All eight individual patch hashes matched their downloaded contents.

The PHP 7.2 preparation command was exercised against the original affected files retained from a prior supplier source build. The prerequisite and main backport applied with zero fuzz. Its 16 security-patch target files matched the previously patched source files byte-for-byte. The prerequisite changed the additional `Zend/zend_string.h` file as expected.

The previous operational remediation rebuilt and deployed multiple PHP branches on CentOS 7 with focused compatibility checks. That preceded this CLI. It is context for the procedure, not evidence that this CLI has rebuilt every branch or every supplier package.

## Fresh Docker retest on 23 October 2026

Commit `5fb169f81f749511a5e8683b81ad022b7f7570c6` was tested in fresh images built with `--pull --no-cache` from the repository Dockerfiles.

| Environment | Suite | Native fixture build/install | Stock PHP inventory and live-process checks |
|---|---|---|---|
| CentOS 7.9, amd64, Python 3.6 | 23 passed, one dpkg-specific skip | Passed, including artifact verification and tamper rejection | Passed with PHP 5.4.16 |
| Ubuntu 18.04, arm64, Python 3.6 | 24 passed | Passed, including artifact verification and tamper rejection | Passed with PHP 7.2.24-0ubuntu0.18.04.17 |

Both environments also downloaded the pinned PHP 7.2 source-packaging archive into an empty cache over verified HTTPS. The prerequisite and security patches applied to real PHP 7.2.34 affected source files with zero fuzz. Both prepared outputs matched the expected patched files.

The stock PHP checks copied the installed CLI into a private temporary directory, ran that copy, and replaced only the temporary executable. Inventory found the installed PHP packages and the explicit runtime path. The audit first observed current code, then returned exit code `3` and marked the old process stale after replacement. Installed PHP executables were not modified.

The PHP 5.4 check covers discovery and process auditing only. There is no PHP 5.4 backport in this catalog. These stock-runtime checks establish discovery, not successful patching. The separate vendor builds below test rebuilt PHP 7.2 packages.

## Full vendor package builds on 23 October 2026

Both builds used real supplier source packages and their native packaging, as an unprivileged user inside disposable Docker containers. The Ubuntu build required the exact-source VM adaptation now included in the CLI. The CentOS build used the original Remi spec and its existing patch stack. No production installation was performed.

| Environment | Supplier source | Generated packages | Installed ELF files verified | Loaded extensions preserved |
|---|---|---|---|---|
| Ubuntu 18.04, arm64 | Canonical `7.2.24-0ubuntu0.18.04.17` | 38 `.deb` and 35 `.ddeb` | 125 | 70 |
| CentOS 7.9, amd64 under emulation | Remi `php72-php-7.2.34-22.remi.src.rpm` | 35 binary RPMs and one source RPM | 125 | 69 |

All generated binary packages, including debug packages, were installed in their respective test containers. Version and ELF checks matched the exact candidate archives. On CentOS, all 63 existing package configuration files retained their hashes. RPM dependency/provide/conflict/obsolete metadata matched the vendor packages after normalizing the release suffix, except SOAP no longer required the versioned `libm.so.6(GLIBC_2.2.5)` symbol; its unversioned libm requirement remained.

Both installations passed ICU normalization/collation/date checks, PDO SQLite queries, extension/PDO-driver/ICU-version/startup-diagnostic parity, normal multipart uploads, persistent sessions, FPM configuration validation, two bounded CGI parser-OOM cases, actual Apache mod_php and FPM requests, and FPM worker replacement after parser OOM. Process auditing observed current Apache/FPM code. These are compatibility and failure-path checks, not a complete exploit test.

The CentOS vendor suite reported 15,939 tests: 9,250 passed, 6,637 skipped, 34 expected failures, and 18 failures. Eight failures expect the upload-progress callbacks intentionally disabled by the minimal backport; one expects the previous OOM diagnostic formatting. Each of the other nine failures reproduced with both the original vendor CLI and the rebuilt CLI: one timezone-data expectation, four OpenSSL certificate checks, three filesystem/file-descriptor checks, and one process-title check. The suite was not entirely green. The vendor spec permits packaging despite test failures, so its exit status alone was not accepted as validation.

Ubuntu's vendor packaging disables its bundled suite on arm64. A separate 3,110-test selection covered Zend, basic/language/security, and session tests using both the original and rebuilt CLI/CGI. The original run had three failures, and the patched run had twelve: the same three session-path expectations plus the eight upload-progress expectations and one OOM formatting change described above. There were 82 skips and nine expected failures in each run. No unexplained new failures remained in this selection. This was not the complete upstream suite.

The Ubuntu build was repeated in full. All 73 generated archives were collected, including debug packages and unchanged package bytes. Replaying VM preparation with the rebuilt bootstrap produced the same derived VM patch SHA256. The complete vendor package set is not claimed bit-for-bit reproducible.

The current unit suite has 29 tests: all pass on Bionic; CentOS skips the one dpkg-specific test. Native fixture build/install, installed-file verification, deliberate tamper rejection, and repeated Debian artifact collection also pass on both platforms where applicable. See [the vendor build recipe](vendor-builds.md) for inputs, commands, and environment limits.

## Checks the operator must still perform

- Retrieve and authenticate the exact supplier source and existing patch stack.
- Resolve build dependencies and compile every selected PHP branch for the actual target architecture and library ABI.
- Inspect native test logs and explain unexpected failures. A packaging exit code alone is insufficient.
- Test the actual extensions, proprietary loaders, serving SAPIs, multipart uploads, and sessions.
- Inventory custom prefixes, copied jails, administrative interfaces, workers, and containers.
- Establish backups and rollback, simulate transactions, preserve configs, replace old processes, and test applications.

The full vendor results cover only the two PHP 7.2 source versions and architectures listed above. Other PHP branches, proprietary loaders, application/database integrations, production service managers, and other architectures still require testing. No universal supplier/source compatibility, exploit resistance certification, general EOL support, or automated production rollout is claimed.
