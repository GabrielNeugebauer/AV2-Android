#!/usr/bin/env bash
# Installs the decoders on a phone (scripts/install_phone.sh), checks every test-stream decode against its reference MD5
# and runs checkasm.
#   dav2d: the dav2d-test-data streams (AVM v15 conformance), then checkasm.
#   dav1d: checkasm-dav1d, then the AV1 streams in streams/av1-test/ (or $AV1_STREAMS) that have a .md5, if any.
# Usage: scripts/phone_smoke_test.sh <adb serial> [dav2d|dav1d|all]   (run from the AV2-Android folder)
# "all" (default) tests every decoder that is built.
set -euo pipefail
SERIAL=${1:?usage: $0 <adb serial> [dav2d|dav1d|all]}
WHAT=${2:-all}
D=/data/local/tmp/av2
AV1_STREAMS=${AV1_STREAMS:-streams/av1-test}
ADB=(adb -s "$SERIAL")

scripts/install_phone.sh "$SERIAL" "$WHAT"
# Decoders on the phone, as listed by install_phone.sh
on_phone=$("${ADB[@]}" shell -n "cat $D/VERSIONS" | awk '{print $1}')
wanted() { { [ "$WHAT" = all ] || [ "$WHAT" = "$1" ]; } && grep -qx "$1" <<< "$on_phone"; }

# Decodes each "<file> <md5>" line of stdin with --verify; streams must already be in $D/streams.
verify_streams() {
    local dec=$1 extra=$2 pass=0 fail=0 f md5
    while read -r f md5; do
        if "${ADB[@]}" shell -n "$D/$dec -q --threads 1 $extra -i $D/streams/$f --verify $md5" >/dev/null 2>&1; then
            pass=$((pass + 1)); echo "PASS $f"
        else
            fail=$((fail + 1)); echo "FAIL $f"
        fi
    done
    echo "Streams: $pass passed, $fail failed"
}

if wanted dav2d; then
    echo "== dav2d"
    "${ADB[@]}" push src/dav2d-test-data/avm/*.obu "$D/streams/" >/dev/null
    # Expected MD5s, taken from the test-data meson file
    sed -n "s/.*files('\([^']*\)'), '\([0-9a-f]*\)'.*/\1 \2/p" src/dav2d-test-data/avm/meson.build > build/expected_md5.txt
    verify_streams dav2d --filmgrain=1 < build/expected_md5.txt
    "${ADB[@]}" shell -n "$D/checkasm 2>&1" | tail -1
fi

if wanted dav1d; then
    echo "== dav1d"
    if "${ADB[@]}" shell -n "test -x $D/checkasm-dav1d"; then
        "${ADB[@]}" shell -n "$D/checkasm-dav1d 2>&1" | tail -1
    else
        echo "checkasm-dav1d is not on the phone (scripts/build_dav1d.sh builds it)"
    fi
    list=()
    for s in "$AV1_STREAMS"/*.ivf; do
        [ -f "${s%.ivf}.md5" ] || continue
        "${ADB[@]}" push "$s" "$D/streams/" >/dev/null
        list+=("$(basename "$s") $(cut -d' ' -f1 "${s%.ivf}.md5")")
    done
    if [ ${#list[@]} -gt 0 ]; then
        printf '%s\n' "${list[@]}" | verify_streams dav1d ""
    else
        echo "No AV1 streams with .md5 in $AV1_STREAMS/: skipped the dav1d decode check"
    fi
fi
