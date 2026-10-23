# Reproduce the tested vendor builds

Use disposable containers or VMs. These commands install packages only in the test environment. Build and source-preparation commands run as an unprivileged `builder` user; dependency and candidate installation run as root. Mount this repository at `/opt/toolkit`, create a builder-owned `/work`, and use Docker `--init` so dependency-installation subprocesses are reaped. Neither the CLI nor these tests manage production services.

The regular CI jobs use synthetic native packages. Full PHP builds are separate, expensive integration checks; they are not automatically repeated by CI.

## Ubuntu 18.04 arm64

Enable the matching Bionic binary and `deb-src` archive entries. Authenticate the archive metadata with APT. Resolve dependencies with `apt-get build-dep php7.2` and install `php7.2-cli`, Python 3, `dpkg-dev`, `quilt`, and `patch`. In a container, use the normal `policy-rc.d` mechanism to prevent dependency packages starting services. Do not disable signature verification.

Fetch the exact source with `apt-get source php7.2=7.2.24-0ubuntu0.18.04.17` and check all input files against the matching authenticated source index. The tested files were:

| File | SHA256 |
|---|---|
| `php7.2_7.2.24.orig.tar.xz` | `a6a6cc03388060aa5f8f9e45799b72bce1c7ed7b9d7b3f1187787202aad91d25` |
| `php7.2_7.2.24-0ubuntu0.18.04.17.debian.tar.xz` | `5db339d1579ddabb14492a09cbb008427f964f390685dc082db631b6bd76c52c` |
| `php7.2_7.2.24-0ubuntu0.18.04.17.dsc` | `a974ebfd8d9f0368a839013749e7fcf30b9d635dda5616ab830597ecfe963004` |

Install the vendor's 38 binary packages before taking a runtime baseline, so optional-extension parity is meaningful. Then, as `builder`:

```sh
cd /opt/toolkit
python3 tests/vendor_runtime.py snapshot --php /usr/bin/php7.2 \
  --output /work/baseline-runtime.json
python3 rebuildctl prepare --branch 7.2 \
  --source /work/source/php7.2-7.2.24 --output /work/prepared
DEB_BUILD_OPTIONS=parallel=2 python3 rebuildctl build \
  --tree /work/prepared --output /work/artifacts --in-builder
```

The prerequisite is already present on this Canonical source. The generated core patch SHA256 is `a38d6955bf98891f6e03cf09483481ec5d4f70f101dab2926c071f2f6b09b34e`; the derived VM patch SHA256 is `6e6545aeff2ec8192976e1fd8e0ce319299681ee3aba4b6624466f26e2c65e13`. Preparation metadata records the six checked VM input hashes and the generator. The source input remains unchanged.

As root, generate the manifest, install the candidates, and verify them:

```sh
python3 /opt/toolkit/rebuildctl manifest /work/artifacts/*.deb /work/artifacts/*.ddeb \
  --output /work/manifest.json
dpkg -i /work/artifacts/*.deb /work/artifacts/*.ddeb
python3 /opt/toolkit/rebuildctl verify --manifest /work/manifest.json \
  --output /work/installed-verification.json
python3 /opt/toolkit/tests/vendor_runtime.py check --php /usr/bin/php7.2 \
  --cgi /usr/bin/php-cgi7.2 --fpm /usr/sbin/php-fpm7.2 \
  --baseline /work/baseline-runtime.json --output /work/runtime-verification.json
```

Then run `python3 /opt/toolkit/tests/vendor_sapi.py /work/sapi-verification.json` as `builder`. It needs the installed Apache and FPM packages and uses private local listeners and configuration files.

For the extra PHPT selection, preserve the original vendor CLI and CGI before installation. Copy `run-tests.php`, `tests/`, `Zend/tests/`, `ext/session/tests/`, and `sapi/cli/tests/` from the source to separate builder-owned test trees. Give each tree a writable private `sessions/` directory. Run the following once with the original executables and once with the rebuilt executables, from the respective test tree:

```sh
NO_INTERACTION=1 REPORT_EXIT_STATUS=1 SKIP_ONLINE_TESTS=1 SKIP_SLOW_TESTS=1 \
TEST_PHP_EXECUTABLE="$tested_php" TEST_PHP_CGI_EXECUTABLE="$tested_cgi" \
"$tested_php" -n run-tests.php -n -d "session.save_path=$PWD/sessions" \
  -p "$tested_php" -q Zend/tests tests/basic tests/lang tests/security ext/session/tests
```

Set `tested_php` and `tested_cgi` to the appropriate absolute paths. Preserve both runs' logs and failure outputs; the known failures are explained in validation. Supplying a private session path itself changes three upstream empty-path expectations.

## CentOS 7 amd64

The test reused a matching EL7 dependency filesystem from an earlier builder. It compiled the original source package afresh; it was not a clean dependency bootstrap from a stock CentOS image. The repositories were the CentOS vault, EPEL archive, and public Remi repositories, with package signature checking enabled. Build dependencies must match the vendor spec, including the Remi SCL macros, devtoolset-8 compiler, `libicu69-devel` 69.1 and `gd3php-devel` 2.3.3. An arbitrary newer ICU development package is not interchangeable.

Download the [original Remi source RPM](https://rpms.remirepo.net/SRPMS/php72-php-7.2.34-22.remi.src.rpm), authenticate its signature using the supplier's independently verified key, and retain the input. The tested SHA256 was `9fedd5d18845cbeced5f86a64efb8f8fc4bb05547bf32804ddaa94080b401e77`; RPM reported its signature valid with key ID `2a0948e4`. A short key ID alone is not a trust anchor.

Install all stock binary subpackages before taking the baseline. As `builder`:

```sh
cd /opt/toolkit
rpm -ivh --nodeps --define '_topdir /work/vendor' /work/vendor.src.rpm
python3 tests/vendor_runtime.py snapshot --php /opt/remi/php72/root/usr/bin/php \
  --output /work/baseline-runtime.json
. /opt/rh/devtoolset-8/enable
python3 rebuildctl prepare-rpm --branch 7.2 \
  --spec /work/vendor/SPECS/php.spec --sources /work/vendor/SOURCES \
  --output /work/prepared --define 'scl php72' --define 'dist .el7.remi' \
  --define '_smp_mflags -j2'
python3 rebuildctl build --tree /work/prepared \
  --output /work/artifacts --in-builder
```

Keep the spec's normal checks enabled and inspect the failures individually. The tested build emitted filter-macro warnings from other coinstalled SCL build profiles and debug-source warnings. A comparison of all runtime subpackage dependencies/provides/conflicts/obsoletes found only the SOAP symbol-requirement difference documented in [validation](validation.md). Use a builder containing only the required SCL profile when resolving dependencies from scratch.

As root:

```sh
python3 /opt/toolkit/rebuildctl manifest /work/artifacts/*.x86_64.rpm \
  --output /work/manifest.json
rpm -Uvh /work/artifacts/*.x86_64.rpm
python3 /opt/toolkit/rebuildctl verify --manifest /work/manifest.json \
  --output /work/installed-verification.json
python3 /opt/toolkit/tests/vendor_runtime.py check \
  --php /opt/remi/php72/root/usr/bin/php \
  --cgi /opt/remi/php72/root/usr/bin/php-cgi \
  --fpm /opt/remi/php72/root/usr/sbin/php-fpm \
  --baseline /work/baseline-runtime.json --output /work/runtime-verification.json
```

Run the same `vendor_sapi.py` command as `builder`. Source RPMs are retained for provenance and excluded from installed-binary manifests.

## Retain evidence

Keep the authenticated supplier inputs, dependency package inventory, `.rebuild-prepared.json`, generated patch/spec or quilt changes, build logs, candidate archives, manifests, original and rebuilt runtime snapshots, PHPT logs/diffs, and SAPI reports. Preserve an original CLI/CGI and compatible extension directory if comparing vendor tests after installation. Do not replace an old CLI's extensions with newly built modules during the comparison.

Do not publish operational configuration or private inventory reports with these artifacts. See [validation](validation.md) for the exact test counts, explained failures, and remaining coverage limits.
