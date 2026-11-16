#!/usr/bin/env bash
# Builds dav1d (AV1, for the comparison with AV2) in the same layout as dav2d:
#   arm64, armv7: build/dav1d-<arch> (release decoder, tools/dav1d) and build/dav1d-<arch>-checkasm (-Dtrim_dsp=false)
#   host:         build/dav1d-x86 for the PC, to compute the reference MD5 of AV1 streams
# Usage: scripts/build_dav1d.sh [arm64|armv7|host]   (without an argument, in a terminal, it asks)
# The host build needs nasm for its x86 assembly. NOASM=1 builds plain C instead (same output, slower, no checkasm).
# Re-running only rebuilds what changed. Set RECONFIGURE=1 after changing env.sh or the NDK.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ $# -eq 0 ] && [ -t 0 ]; then
    echo "Arquitetura: [1] arm64  [2] armv7  [3] host (PC)"
    read -rp "Selecione (em branco = 1): " choice
    case $choice in 2) ARCH=armv7 ;; 3) ARCH=host ;; *) ARCH=arm64 ;; esac
else
    ARCH=${1:-arm64}
fi
source scripts/env.sh
SRC=src/dav1d
[ -d "$SRC" ] || { echo "$SRC missing: run scripts/fetch_sources.sh" >&2; exit 1; }
COMMON=(--buildtype release -Ddefault_library=static)

setup() {  # setup <builddir> <options...>
    local dir=$1; shift
    if [ ! -f "$dir/build.ninja" ]; then
        "$MESON" setup "$dir" "$SRC" "$@"
    elif [ -n "${RECONFIGURE:-}" ]; then
        "$MESON" setup --reconfigure "$dir" "$SRC" "$@"
    fi
}

if [ "$ARCH" = host ]; then
    TESTS=true
    if [ -n "${NOASM:-}" ]; then
        # checkasm has nothing to check without assembly, and its own x86 file still needs nasm
        echo "Warning: NOASM=1, building dav1d for the PC without assembly or checkasm" >&2
        COMMON+=(-Denable_asm=false) TESTS=false
    elif ! command -v nasm >/dev/null; then
        echo "nasm not found: install it (sudo apt install nasm), or run with NOASM=1 for a plain C build" >&2
        exit 1
    fi
    setup build/dav1d-x86 "${COMMON[@]}" -Denable_tools=true -Denable_tests=$TESTS -Dtestdata_tests=false
    ninja -C build/dav1d-x86 -j "$JOBS"
    file build/dav1d-x86/tools/dav1d
    exit 0
fi

CROSS=build/android-$ARCH.meson
scripts/make_cross_file.sh "$ARCH" "$CROSS"
setup "build/dav1d-$ARCH" --cross-file "$CROSS" "${COMMON[@]}" \
    -Denable_tools=true -Denable_tests=true -Dtestdata_tests=false
ninja -C "build/dav1d-$ARCH" -j "$JOBS"
setup "build/dav1d-$ARCH-checkasm" --cross-file "$CROSS" "${COMMON[@]}" \
    -Denable_tools=false -Denable_tests=true -Dtrim_dsp=false
ninja -C "build/dav1d-$ARCH-checkasm" -j "$JOBS" tests/checkasm
file "build/dav1d-$ARCH/tools/dav1d" "build/dav1d-$ARCH-checkasm/tests/checkasm"
