# Validation scope

This is the first public version. Treat it as an operator toolkit with an explicit validation boundary.

## Automated checks

The unit suite covers patch direction and idempotency, failed preparation cleanup, source preservation, symlink/traversal rejection, cached archive tampering, report permissions, root/build-OS guards, Debian/Remi runtime names, stale mapped-module device/inode detection, package hardlinks, installed-file tampering, and CLI error codes.

The Ubuntu 18.04 container also creates and reads an actual Debian binary package. That one format-specific unit test is skipped on CentOS, where dpkg is absent. Both native container jobs exercise the actual native format separately.

Each native job does the following:

1. Run the unit suite on the distribution's Python 3.6.
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

## Checks the operator must still perform

- Retrieve and authenticate the exact supplier source and existing patch stack.
- Resolve build dependencies and compile every selected PHP branch for the actual target architecture and library ABI.
- Inspect native test logs and explain unexpected failures. A packaging exit code alone is insufficient.
- Test the actual extensions, proprietary loaders, serving SAPIs, multipart uploads, and sessions.
- Inventory custom prefixes, copied jails, administrative interfaces, workers, and containers.
- Establish backups and rollback, simulate transactions, preserve configs, replace old processes, and test applications.

No full PHP rebuild on Ubuntu 18.04 is claimed for the initial CLI. No universal supplier/source compatibility, exploit resistance certification, general EOL support, or automated production rollout is claimed.
