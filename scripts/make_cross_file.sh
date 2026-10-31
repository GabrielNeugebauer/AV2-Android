#!/usr/bin/env bash
# Writes a meson cross file for the Android NDK set in scripts/env.sh.
# Usage: scripts/make_cross_file.sh <arm64|armv7> <out.meson>   (run from the AV2-Android folder)
# armv7 is for phones that only run 32-bit code (e.g. some Helio P22 ROMs).
set -euo pipefail
ARCH=${1:?usage: $0 <arm64|armv7> <out.meson>} OUT=${2:?usage: $0 <arm64|armv7> <out.meson>}
source "$(dirname "$0")/env.sh"
case $ARCH in
    arm64) TRIPLE=aarch64-linux-android FAMILY=aarch64 CPU=aarch64 ;;
    armv7) TRIPLE=armv7a-linux-androideabi FAMILY=arm CPU=armv7 ;;
    *) echo "unknown arch '$ARCH' (arm64 or armv7)" >&2; exit 1 ;;
esac
[ -x "$NDK_BIN/$TRIPLE$ANDROID_API-clang" ] || { echo "no $TRIPLE$ANDROID_API-clang in $NDK_BIN; check ANDROID_NDK" >&2; exit 1; }
NOTE=""
[ "$ANDROID_API" = 29 ] && NOTE=" = Android 10, so the same binary also runs on older phones"
mkdir -p "$(dirname "$OUT")"
TMP=$(mktemp)
chmod 644 "$TMP"
cat > "$TMP" <<END
# Android $ARCH (API $ANDROID_API$NOTE)
[binaries]
c = '$NDK_BIN/$TRIPLE$ANDROID_API-clang'
cpp = '$NDK_BIN/$TRIPLE$ANDROID_API-clang++'
ar = '$NDK_BIN/llvm-ar'
strip = '$NDK_BIN/llvm-strip'
pkg-config = 'false'

[host_machine]
system = 'android'
cpu_family = '$FAMILY'
cpu = '$CPU'
endian = 'little'

[properties]
needs_exe_wrapper = true
END
# Replaced only when it changes, so ninja does not reconfigure the builds for nothing
if cmp -s "$TMP" "$OUT"; then rm "$TMP"; else mv "$TMP" "$OUT"; fi
