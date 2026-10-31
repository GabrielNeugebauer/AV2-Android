#!/usr/bin/env bash
# Builds the AVM encoder and reference decoder (avmenc, avmdec) for the PC in build/avm-x86, optimized and multithreaded.
# Usage: scripts/build_avm.sh   (paths relative to the AV2-Android folder; BUILD_DIR=<dir> builds elsewhere)
# Two traps: the av2-normative branch builds plain C unless AVM_TARGET_CPU is set, and -DENABLE_EXAMPLES=0 also
# drops avmenc and avmdec. The build compiles TensorFlow Lite too, so it takes several minutes.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
SRC=$PWD/src/avm BUILD_DIR=${BUILD_DIR:-build/avm-x86}
[ -d "$SRC" ] || { echo "$SRC missing: run scripts/fetch_sources.sh" >&2; exit 1; }
cmake -S "$SRC" -B "$BUILD_DIR" -DCMAKE_BUILD_TYPE=Release -DAVM_TARGET_CPU=x86_64 -DCONFIG_MULTITHREAD=1 \
    -DENABLE_TESTS=0 -DENABLE_DOCS=0
if [ -n "${CONFIGURE_ONLY:-}" ]; then exit 0; fi
make -C "$BUILD_DIR" -j "$JOBS" avmenc avmdec
"$BUILD_DIR/avmdec" --help 2>&1 | head -1
