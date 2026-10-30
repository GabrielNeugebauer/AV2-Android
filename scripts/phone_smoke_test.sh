#!/usr/bin/env bash
# Pushes dav2d, checkasm and the dav2d-test-data streams to a phone, then checks every
# decode against its reference MD5 and runs checkasm.
# Usage: scripts/phone_smoke_test.sh <adb serial>   (run from the AV2-Android folder)
set -euo pipefail
SERIAL=${1:?usage: $0 <adb serial>}
D=/data/local/tmp/av2
ADB=(adb -s "$SERIAL")

"${ADB[@]}" shell "mkdir -p $D/streams"
"${ADB[@]}" push build/dav2d-arm64/tools/dav2d "$D/dav2d" >/dev/null
"${ADB[@]}" push build/dav2d-arm64-checkasm/tests/checkasm "$D/checkasm" >/dev/null
"${ADB[@]}" push src/dav2d-test-data/avm/*.obu "$D/streams/" >/dev/null
"${ADB[@]}" shell "chmod 755 $D/dav2d $D/checkasm"

# Expected MD5s, taken from the test-data meson file
sed -n "s/.*files('\([^']*\)'), '\([0-9a-f]*\)'.*/\1 \2/p" src/dav2d-test-data/avm/meson.build > build/expected_md5.txt

pass=0; fail=0
while read -r f md5; do
    if "${ADB[@]}" shell -n "$D/dav2d -q --threads 1 --filmgrain=1 -i $D/streams/$f --verify $md5" >/dev/null 2>&1; then
        pass=$((pass + 1)); echo "PASS $f"
    else
        fail=$((fail + 1)); echo "FAIL $f"
    fi
done < build/expected_md5.txt
echo "Streams: $pass passed, $fail failed"

"${ADB[@]}" shell -n "$D/checkasm 2>&1" | tail -1
