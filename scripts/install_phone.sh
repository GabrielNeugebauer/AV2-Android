#!/usr/bin/env bash
# Pushes the decoders (dav2d, dav1d) and their checkasm builds to a phone, in /data/local/tmp/av2, and records the
# source commit of each one in /data/local/tmp/av2/VERSIONS.
# Usage: scripts/install_phone.sh <adb serial> [dav2d|dav1d|all] [--arch arm64|armv7]   (run from the AV2-Android folder)
# "all" (default) installs every decoder that is built and skips the others; naming one fails if it is not built.
# Without --arch, the phone's ABI list picks it (arm64-v8a -> arm64, otherwise armv7).
set -euo pipefail
USAGE="usage: $0 <adb serial> [dav2d|dav1d|all] [--arch arm64|armv7]"
SERIAL=${1:?$USAGE}
shift
WHAT=all ARCH=
while [ $# -gt 0 ]; do
    case $1 in
        dav2d | dav1d | all) WHAT=$1 ;;
        --arch) ARCH=${2:?$USAGE}; shift ;;
        *) echo "$USAGE" >&2; exit 2 ;;
    esac
    shift
done
D=/data/local/tmp/av2
ADB=(adb -s "$SERIAL")

if [ -z "$ARCH" ]; then
    case $("${ADB[@]}" shell -n getprop ro.product.cpu.abilist) in
        *arm64-v8a*) ARCH=arm64 ;;
        *) ARCH=armv7 ;;
    esac
fi
case $ARCH in arm64 | armv7) ;; *) echo "$USAGE" >&2; exit 2 ;; esac

"${ADB[@]}" shell -n "mkdir -p $D/streams"
installed=()
for dec in dav2d dav1d; do
    [ "$WHAT" = all ] || [ "$WHAT" = "$dec" ] || continue
    bin=build/$dec-$ARCH/tools/$dec
    if [ ! -x "$bin" ]; then
        if [ "$WHAT" = "$dec" ]; then
            echo "$bin is not built; run scripts/build_$dec.sh first" >&2
            exit 1
        fi
        echo "Skipping $dec: $bin is not built (scripts/build_$dec.sh)"
        continue
    fi
    "${ADB[@]}" push "$bin" "$D/$dec" >/dev/null
    # dav2d's checkasm keeps the plain name, which older scripts expect
    checkasm=build/$dec-$ARCH-checkasm/tests/checkasm
    target=$D/checkasm
    [ "$dec" = dav1d ] && target=$D/checkasm-dav1d
    if [ -x "$checkasm" ]; then
        "${ADB[@]}" push "$checkasm" "$target" >/dev/null
        "${ADB[@]}" shell -n "chmod 755 $target"
    else
        echo "No $checkasm: checkasm for $dec not installed (scripts/build_$dec.sh builds it)"
    fi
    "${ADB[@]}" shell -n "chmod 755 $D/$dec"
    installed+=("$dec")
done
if [ ${#installed[@]} -eq 0 ]; then
    echo "Nothing to install for $ARCH: run scripts/build_dav2d.sh or scripts/build_dav1d.sh first" >&2
    exit 1
fi

# VERSIONS has one line per decoder on the phone: name, source commit, arch, install date.
# Lines of decoders not installed now are kept.
now=$(date -Iseconds)
versions=$("${ADB[@]}" shell -n "cat $D/VERSIONS 2>/dev/null" | tr -d '\r' || true)
for dec in "${installed[@]}"; do
    commit=$(git -C "src/$dec" rev-parse --short HEAD)
    [ -z "$(git -C "src/$dec" status --porcelain --untracked-files=no)" ] || commit=$commit-dirty
    versions=$(printf '%s\n' "$versions" | grep -v "^$dec " || true)
    versions=$(printf '%s\n%s %s %s %s' "$versions" "$dec" "$commit" "$ARCH" "$now")
done
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
printf '%s\n' "$versions" | sed '/^$/d' | sort > "$tmp"
"${ADB[@]}" push "$tmp" "$D/VERSIONS" >/dev/null

for dec in "${installed[@]}"; do
    echo "$dec on the phone: $("${ADB[@]}" shell -n "$D/$dec --version 2>&1" | tr -d '\r')"
done
echo "$D/VERSIONS:"
"${ADB[@]}" shell -n "cat $D/VERSIONS"
