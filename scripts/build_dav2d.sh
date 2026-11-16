#!/usr/bin/env bash
# Cross-compiles dav2d for Android: build/dav2d-<arch> (release decoder, tools/dav2d, used for benchmarks) and
# build/dav2d-<arch>-checkasm (-Dtrim_dsp=false: checkasm needs the plain C functions that release builds remove).
# Usage: scripts/build_dav2d.sh [arm64|armv7]   (without an argument, in a terminal, it asks)
# Re-running only rebuilds what changed. Set RECONFIGURE=1 after changing env.sh or the NDK.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ $# -eq 0 ] && [ -t 0 ]; then
    echo "Arquitetura: [1] arm64  [2] armv7"
    read -rp "Selecione (em branco = 1): " choice
    case $choice in 2) ARCH=armv7 ;; *) ARCH=arm64 ;; esac
else
    ARCH=${1:-arm64}
fi
source scripts/env.sh
SRC=src/dav2d CROSS=build/android-$ARCH.meson
[ -d "$SRC" ] || { echo "$SRC missing: run scripts/fetch_sources.sh" >&2; exit 1; }
scripts/make_cross_file.sh "$ARCH" "$CROSS"

setup() {  # setup <builddir> <options...>
    local dir=$1; shift
    if [ ! -f "$dir/build.ninja" ]; then
        "$MESON" setup "$dir" "$SRC" --cross-file "$CROSS" "$@"
    elif [ -n "${RECONFIGURE:-}" ]; then
        "$MESON" setup --reconfigure "$dir" "$SRC" --cross-file "$CROSS" "$@"
    fi
}

setup "build/dav2d-$ARCH" --buildtype release -Ddefault_library=static \
    -Denable_tools=true -Denable_tests=true -Dtestdata_tests=false
ninja -C "build/dav2d-$ARCH" -j "$JOBS"
setup "build/dav2d-$ARCH-checkasm" --buildtype release -Ddefault_library=static \
    -Denable_tools=false -Denable_tests=true -Dtrim_dsp=false
ninja -C "build/dav2d-$ARCH-checkasm" -j "$JOBS" tests/checkasm
file "build/dav2d-$ARCH/tools/dav2d" "build/dav2d-$ARCH-checkasm/tests/checkasm"
