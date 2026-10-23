# Legacy Runtime Rebuilder

A small CLI for operators rebuilding legacy PHP after **PHP2Shell**, CVE-2026-109618 and CVE-2026-109619.

It inventories PHP installations, prepares reviewed source backports, runs existing native packaging in a disposable builder, and checks deployed package files and running processes. Python 3.6 or newer. Standard library only. No production package installation or automatic service restarts.

This started with a successful CentOS 7 remediation across multiple PHP branches and a separate ISPConfig jail refresh. The original scripts depended on those machines. This project replaces their paths and package-family assumptions with explicit inputs and conservative failure checks.

**This is an operator toolkit, not a universal one-command fix.** A supplier's patch stack, build dependencies, proprietary extensions, copied runtimes, and service layout still need review. Clean hashes establish artifact identity. They do not independently prove security or application compatibility.

## Get started

Clone this repository onto a workstation or target host. Run commands from its directory:

```sh
python3 rebuildctl --help
python3 rebuildctl patches
sudo python3 rebuildctl inventory --output inventory.json
sudo python3 rebuildctl audit --output processes.json
```

The last two commands are read-only. Root improves access to process maps and jailed runtimes. Reports are created with mode `0600` and refuse to overwrite existing files. They contain package names, runtime paths, hashes, and process IDs. They do not collect environment variables, full command lines, application configuration, or web content. Treat reports as private operational data.

Add a nonstandard runtime path with repeated `--runtime /absolute/path/to/php`. Automatic discovery covers common system paths, Remi SCL paths, `/opt/php*`, and the usual ISPConfig jailed CLI layout. Arbitrary hosting panels, nested containers, and embedded runtimes need separate inventory. Run container inventory inside the container.

Exit codes are `0` for a completed check, `2` for an input/tool/build error, and `3` for a mismatch or incomplete process audit. An audit with no observed runtime returns `3`. An inventory is a discovery report, not a verdict that the host is patched.

## Check vendor packages first

Use a fixed distribution-matching vendor package when available. Canonical lists Ubuntu 18.04 PHP 7.2 fixed in `7.2.24-0ubuntu0.18.04.17+esm14` through Ubuntu Pro as of 22 October 2026. This does not cover another supplier's PHP package. Recheck both [Canonical CVE pages](https://ubuntu.com/security/CVE-2026-109618) and [the second CVE](https://ubuntu.com/security/CVE-2026-109619).

Read the [official PHP advisory](https://www.php.net/archive/2026.php#2026-10-21-5). This tool does not suggest global upload blocking or treat an INI mitigation as a complete fix.

## Prepare source backports

The catalog covers PHP **5.6, 7.1, 7.2, 7.4, 8.0, and 8.1**. It records the exact Surý source archive URL, archive SHA256, and individual patch hashes. Patch code is downloaded on demand from its publisher, not bundled or relicensed here. Python's default HTTPS certificate verification remains enabled.

PHP 7.1/7.2 include the `ZSTR_MAX_LEN` prerequisite. Every patch must apply with zero fuzz or pass a complete reverse dry-run showing it is already present. Partial or incompatible patches fail. Older micro releases and different vendor stacks may require an independently reviewed adaptation. No patch set is provided for PHP 7.0 or older unsupported branches outside this list.

**The minimal legacy backports disable session upload-progress callbacks.** Normal multipart uploads remain available, but applications using PHP's session-based progress feature need review. The INI setting can still display enabled.

For a trusted extracted upstream tree:

```sh
python3 rebuildctl prepare \
  --branch 7.2 --source /work/vendor-php-source \
  --output /work/patched-php-source
```

The input is preserved. The output must be a new directory outside the input. A failed preparation leaves no final output tree. `prepare` accepts already extracted sources, so source retrieval, archive safety, publisher signature checks, and preservation of the supplier's patch stack remain the operator's responsibility.

An upstream-only tree can be compiled with its existing build recipe, but the `build` command requires native packaging. Preserve the original configure arguments, extension ABI, and install prefix for unpackaged PHP.

## Rebuild Ubuntu 18.04 packages

Work inside a disposable Bionic builder of the target architecture. Install the supplier's build dependencies there. Use its actual source package, not newer Ubuntu binary packages. Debian preparation requires `3.0 (quilt)` source format, `dpkg-dev`, `quilt`, and `patch`.

```sh
# First extract and verify the supplier's source package in this builder.
# Run the following commands as an unprivileged build user.
python3 rebuildctl prepare \
  --branch 7.2 --source /work/vendor-source \
  --output /work/patched-source --revision rebuild1

python3 rebuildctl build \
  --tree /work/patched-source --output /work/packages --in-builder
```

The tool adds the backports to the existing quilt stack and appends a distinct changelog version suffix. It checks that the new Debian version sorts above the source version. The native build uses `dpkg-buildpackage -us -uc -b`, retaining the package's normal checks. No dependency installation is attempted by the CLI.

Canonical's Bionic PHP 7.2.24 and Surý's PHP 7.2.34 differ. Version `7.2.24-0ubuntu0.18.04.17` has a narrowly pinned adaptation: the CLI checks six vendor VM input hashes, rebases the allocation guards from the published patch, and regenerates the interpreter with the vendor's `Zend/zend_vm_gen.php`. This requires the `php7.2-cli` bootstrap package in the builder. It runs with `-n` to ignore PHP INI files. Opcode definitions must remain unchanged, and the generated diff must contain only the published allocation guards. Unknown input files are refused.

Other source baselines still need an independently reviewed adaptation if the standard patches do not match. Do not force failed hunks into place. See [the operator procedure](docs/operations.md).

## Rebuild CentOS 7 packages

Use a disposable EL7 builder with the original supplier's development libraries and toolchain. Extract a trusted, verified SRPM into a dedicated RPM build tree using your normal tooling. Supply its spec, SOURCES directory, and required macro definitions:

```sh
python3 rebuildctl prepare-rpm \
  --branch 7.2 --spec /work/vendor/SPECS/php.spec \
  --sources /work/vendor/SOURCES --output /work/patched-rpm \
  --define 'scl php72' --define 'dist .el7.remi'

python3 rebuildctl build \
  --tree /work/patched-rpm --output /work/packages --in-builder
```

The tool copies the source files, gives the release a distinct suffix, and appends the verified backports after the vendor's `%prep` steps. It requires one plain `%prep` and one plain `%build` section. Complex specs are refused. Macro definitions are arguments to RPM, never interpolated into a shell command. RPM spec files themselves are executable build code, so use trusted inputs.

Activate a compatible compiler environment before building. Do not move a new compiler or ICU development stack onto production. Build as a non-root user. `--in-builder` is an operator assertion, not a sandbox. The CLI checks the builder OS but cannot prove that a disposable container or VM surrounds it.

## Verify exact package artifacts

Select the exact binary packages intended for the host. Exclude source RPMs and uninstalled debug/development packages:

```sh
python3 rebuildctl manifest /work/packages/php-example.rpm \
  --output manifest.json

# Transfer the reviewed manifest with its trusted candidate artifacts.
# After the operator installs those packages:
sudo python3 rebuildctl verify --manifest manifest.json
sudo python3 rebuildctl audit
```

The same commands accept `.deb` files and optional `.ddeb` debug packages. Debian builds retain both types. Repeated builds can reproduce identical package bytes; the CLI still collects packages that the native build replaced. `manifest` reads ELF payloads without extracting archive paths onto disk. `verify` checks installed package versions and SHA256 hashes against that manifest. Include all installed packages rebuilt from each affected source family. A hand-selected subset cannot establish full-host coverage.

The manifest records candidate archive hashes, but it is not a signature. Transfer it through a trusted channel and retain build/source provenance. Before installation, verify the candidate files themselves against those recorded archive hashes. The tool does not attest an untrusted build.

The process audit recognizes versioned Debian and Remi executable names, resolves common jail paths, and checks mapped PHP module device/inode identity. It reports unreadable relevant processes as incomplete. `current-on-disk` means the observed processes use current files. Use `verify` as well to correlate those files with candidate artifacts. Never equate either result with an independent vulnerability assessment.

## Complete the rollout

The operator still owns backups, transaction simulation, extension/SAPI tests, jail refresh, worker replacement, and application validation. The [deployment procedure](docs/operations.md) contains the checks learned from the original remediation, including normal upload/session testing and stale long-lived workers.

Ubuntu 18.04 and CentOS 7 still require appropriate ongoing security maintenance. This toolkit addresses two specific PHP vulnerabilities. It does not provide operating-system support or automatic future security updates.

## Test and contribute

```sh
python3 -m unittest discover -s tests -v
docker build -f tests/Dockerfile.ubuntu18 -t lrr-test:ubuntu18 .
docker run --rm --user 0 lrr-test:ubuntu18 sh tests/install-check.sh
docker build --platform linux/amd64 -f tests/Dockerfile.centos7 -t lrr-test:centos7 .
docker run --platform linux/amd64 --rm --user 0 lrr-test:centos7 sh tests/install-check.sh
```

These test images install build tools and an owned C test package only inside disposable containers. Compilation runs as an unprivileged user. The root test harness then installs that fixture, checks package/file identity, and deliberately alters the fixture to check rejection. The CLI retains no automatic production mutation commands. Contributions need a regression test and clear supplier/version coverage. Use synthetic reports without real hostnames, credentials, customer names, or application configuration.

Full vendor PHP 7.2 builds were also tested on Ubuntu 18.04 arm64 and CentOS 7 amd64, including candidate installation and real Apache/FPM requests. See [validation scope](docs/validation.md) for exact versions, explained test failures, and limits, and [the vendor build recipe](docs/vendor-builds.md) to repeat those checks. The regular CI jobs use native fixtures; they do not compile every PHP/vendor combination.

MIT license applies to this project's code. Downloaded patches retain their publishers' licenses and authorship. See [third-party provenance](THIRD_PARTY.md).
