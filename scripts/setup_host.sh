#!/usr/bin/env bash
# Checks the PC tools the build and benchmark scripts need, and creates the Python environment .venv with meson.
# Usage: scripts/setup_host.sh. Installs nothing system-wide: it prints what is missing.
set -uo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
MESON_VERSION=1.12.1
missing=0

check() {  # check <command> <install hint> [optional]
    if command -v "$1" >/dev/null; then
        printf 'OK       %-8s %s\n' "$1" "$("$1" --version 2>&1 | head -1)"
    elif [ -n "${3:-}" ]; then
        printf 'MISSING  %-8s optional: %s\n' "$1" "$2"
    else
        printf 'MISSING  %-8s %s\n' "$1" "$2"; missing=1
    fi
}

check git     "sudo apt install git"
check cmake   "sudo apt install cmake (AVM)"
check make    "sudo apt install build-essential (AVM)"
check ninja   "sudo apt install ninja-build"
check ffmpeg  "sudo apt install ffmpeg (8-bit conversion, AV1 streams)"
check adb     "sudo apt install adb, or Android SDK platform-tools"
check python3 "sudo apt install python3 python3-venv"
check nasm    "sudo apt install nasm (x86 assembly of the PC dav1d build; without it use NOASM=1)" optional

if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv || { echo "MISSING  venv     sudo apt install python3-venv"; missing=1; }
fi
if [ -x .venv/bin/python ] && [ "$(.venv/bin/meson --version 2>/dev/null)" != "$MESON_VERSION" ]; then
    .venv/bin/pip install -q "meson==$MESON_VERSION"
fi
if [ "$("$MESON" --version 2>/dev/null)" = "$MESON_VERSION" ]; then
    echo "OK       meson    $MESON_VERSION ($MESON)"
else
    echo "MISSING  meson    .venv/bin/pip install meson==$MESON_VERSION"; missing=1
fi

if [ -x "$NDK_BIN/aarch64-linux-android$ANDROID_API-clang" ]; then
    echo "OK       NDK      $ANDROID_NDK"
    [ "$(basename "$ANDROID_NDK")" = "$NDK_PINNED" ] || echo "         (pinned version is $NDK_PINNED)"
else
    echo "MISSING  NDK      sdkmanager --sdk_root=\${ANDROID_HOME:-\$HOME/Android/Sdk} 'ndk;$NDK_PINNED'"; missing=1
fi
exit $missing
