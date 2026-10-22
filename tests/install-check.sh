#!/bin/sh
# Only run inside the disposable test image. Installs the owned test fixture.
set -eu
test "$(id -u)" -eq 0
test -f /opt/toolkit/tests/native-smoke.py
su -s /bin/sh builder -c 'cd /opt/toolkit && sh tests/container-check.sh'
if command -v dpkg >/dev/null 2>&1; then
    dpkg -i /tmp/lrr-native/artifacts/*.deb
else
    for package in /tmp/lrr-native/artifacts/*.rpm; do
        case "$package" in *.src.rpm) continue ;; esac
        rpm -Uvh "$package"
    done
fi
test "$(/usr/bin/lrr-fixture)" = patched
python3 rebuildctl verify --manifest /tmp/lrr-native/manifest.json \
    --output /tmp/lrr-native/installed-verification.json
printf 'tampered' >> /usr/bin/lrr-fixture
set +e
python3 rebuildctl verify --manifest /tmp/lrr-native/manifest.json \
    --output /tmp/lrr-native/tamper-verification.json
status=$?
set -e
test "$status" -eq 3
printf '%s\n' 'Native fixture installation, package/file verification, and tamper rejection passed.'
