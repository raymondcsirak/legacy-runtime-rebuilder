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

The PHP 5.4 check covers discovery and process auditing only. There is no PHP 5.4 backport in this catalog. The stock Ubuntu PHP 7.2.24 check likewise establishes runtime discovery, not successful patching of its source package. Neither stock runtime is claimed fixed by these checks.

## Checks the operator must still perform

- Retrieve and authenticate the exact supplier source and existing patch stack.
- Resolve build dependencies and compile every selected PHP branch for the actual target architecture and library ABI.
- Inspect native test logs and explain unexpected failures. A packaging exit code alone is insufficient.
- Test the actual extensions, proprietary loaders, serving SAPIs, multipart uploads, and sessions.
- Inventory custom prefixes, copied jails, administrative interfaces, workers, and containers.
- Establish backups and rollback, simulate transactions, preserve configs, replace old processes, and test applications.

No full PHP rebuild on Ubuntu 18.04 is claimed for the initial CLI. No universal supplier/source compatibility, exploit resistance certification, general EOL support, or automated production rollout is claimed.
