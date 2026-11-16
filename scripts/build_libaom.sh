#!/usr/bin/env bash
# Builds the libaom AV1 encoder and decoder (aomenc, aomdec) for the PC in build/libaom-x86.
# Usage: scripts/build_libaom.sh   (paths relative to the AV2-Android folder; BUILD_DIR=<dir> builds elsewhere)
# This is standard libaom, not the CTC's research-alt-v1-anchor: that anchor changes the bitstream (CONFIG_EXTQUANT,
# CONFIG_REMOVE_DUAL_FILTER), so dav1d could not decode its streams on the phones.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
SRC=$PWD/src/libaom BUILD_DIR=${BUILD_DIR:-build/libaom-x86}
[ -d "$SRC" ] || { echo "$SRC missing: run scripts/fetch_sources.sh libaom" >&2; exit 1; }
cmake -S "$SRC" -B "$BUILD_DIR" -DCMAKE_BUILD_TYPE=Release -DENABLE_TESTS=0 -DENABLE_DOCS=0 -DENABLE_TOOLS=0 \
    -DCONFIG_AV1_HIGHBITDEPTH=1
make -C "$BUILD_DIR" -j "$JOBS" aomenc aomdec
"$BUILD_DIR/aomenc" --help 2>&1 | grep -m1 -i "libaom\|AOMedia"
