#!/bin/sh
set -eu
export PYTHONDONTWRITEBYTECODE=1
export LC_ALL=C LANG=C
python3 -m unittest discover -s tests -v
python3 tests/native-smoke.py
python3 rebuildctl inventory --output /tmp/lrr-native/inventory.json
# No PHP process in this clean builder is an explicit incomplete audit.
set +e
python3 rebuildctl audit --output /tmp/lrr-native/processes.json
status=$?
set -e
test "$status" -eq 3
