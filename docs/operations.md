# Rebuild and deploy without missing a runtime

Use this procedure alongside the CLI. Adapt paths and service names to the host. Do not run commands from another operator's server report verbatim.

## Establish coverage and rollback

1. Confirm host identity, OS, architecture, backups, disk space, and package origins. Check fixed vendor packages first.
2. Inventory all PHP branches, SAPIs, administrative interfaces, workers, and copied jail runtimes. Inspect vhost handlers, FastCGI wrappers, FPM sockets, cron, and process managers. Include inactive installed PHP branches that could be enabled later.
3. Record full package versions, source packages, enabled extensions, PDO drivers, loaded INI paths, startup warnings, proprietary loaders, and required shared-library ABIs.
4. Record each site's HTTP status and redirects. Identify existing failures. Record which runtime serves each application.
5. Retain exact original packages and a verified binary/configuration backup. Preserve ownership, permissions, ACLs, and xattrs. Keep archives private and root-only. Record alternatives and enabled services. Back up jailed runtime copies separately.

Do not assume an archive listing is a full restore test. A binary rollback restores vulnerable PHP. Retain it for deployment regressions and do not delete originals without approval.

## Prepare and validate the build

1. Retrieve the supplier's actual source package and verify publisher signatures and index hashes. Preserve its existing patch set and packaging.
2. Prepare the backports in a new copy. Keep the complete preparation report. Resolve failures against the exact source instead of increasing patch fuzz.
3. Build in an isolated matching OS and architecture using target-compatible libraries. Execute source packaging only as an unprivileged user. Apply CPU/memory limits outside the CLI if the builder shares hardware with production.
4. Inspect the complete native build log and test results. Some vendor packaging can return success after a failing self-test suite. A successful packaging exit is not enough.
5. Extract candidates into a staging root using trusted packaging tools. Check extension/PDO-driver parity, startup diagnostics, loader compatibility, CLI/CGI/FPM startup, and Apache configuration/module loading where used.
6. Test normal multipart uploads and session persistence. Run focused upstream regression tests and bounded parser-OOM tests only in isolation. Preserve logs and explain every unexpected failure.

Do not publish public test endpoints for parser-OOM checks. The tool supplies no exploit or production stress probe.

Older PHP branches can need prerequisites beyond the main security patch. PHP 7.1/7.2 needed `ZSTR_MAX_LEN` in the original deployment. It is included in this catalog and skipped only when the whole prerequisite already applies in reverse.

Compiler and library compatibility matters. An initial legacy PHP 5.6 intl build required a C++ symbol missing from its target and was rejected. A separate PHP 8.2/OpenSSL 1.0.2 build needed a compatibility adaptation. Neither workaround should be applied to a different host without evidence.

## Install the reviewed selection

1. Select every installed binary package rebuilt from each affected source family. Compare full package versions and test ordering against the host, including any epoch. A source version increase alone does not establish ordering against a different installed supplier build.
2. Generate the artifact manifest. Verify package archive SHA256 values through the trusted build record.
3. Simulate the native package transaction. Inspect maintainer scripts for restarts, alternatives changes, config replacement, package removals, and unexpected dependency changes. Choose a restart window before the real transaction.
4. Install only the reviewed matching package selection using existing operational tooling. Preserve local configuration. Keep the exact transaction log.
5. Run `verify` against the reviewed manifest. Do not use the installed package database as the sole source of expected file hashes.

The CLI intentionally does not install packages, migrate repositories, alter upload settings, or restart production services.

## Refresh jails and replace running code

Host package installation does not refresh copied jail binaries. Use the existing Jailkit tooling for the host's actual layout. Copy corresponding PHP binaries, extensions, and required libraries after a separate jail backup. Preserve jailed INI files and compare jail hashes with patched host artifacts.

Restart affected FPM/Apache workers and recycle long-lived CLI processes with their existing managers. Include queues, schedulers, WebSocket servers, and security daemons. Signal Laravel queues as the application user with the correct runtime, then confirm replacements start. Do not clear application queues, locks, or data globally.

An Apache graceful reload may leave the old mod_php module loaded. Confirm mapped module identity after the chosen restart method. A full restart can be necessary.

Inspect actual daemon processes. A SysV service can say `active (exited)` with no live daemon. A stale PID file once blocked a replacement daemon. Prove that its PID is absent before preserving/moving any PID file and restarting.

Run `audit` with sufficient privileges after restart. Investigate every stale or unreadable relevant process. Use additional `--runtime` paths for custom executable names. This audit covers recognizable PHP/server processes and PHP module paths, not all possible embedded runtimes or mount namespaces.

## Validate applications and record limits

Use temporary guarded probes only where the actual routing allows them. Return the minimum runtime identity needed. Do not expose full `phpinfo()` or secrets. Remove probes even if a check fails. Do not bypass an application's ACL to make a probe work.

Compare all site responses with baseline after restart transients settle. Record direct-origin checks separately from public DNS/TLS and authenticated application workflows. Test representative session/login and upload flows when approved credentials are available.

The completion report needs package/source/patch provenance, candidate hashes, installed-file identity, service/worker replacement, jail coverage, per-site handler coverage, HTTP comparison, rollback locations, and any validation gaps. Mention the session upload-progress behavior change. Keep reports private until sanitized.
