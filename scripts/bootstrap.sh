#!/usr/bin/env bash
# Sets up everything from scratch on the PC: tools check, sources, AVM, dav2d and dav1d builds.
# Usage: scripts/bootstrap.sh   (run from the AV2-Android folder; each step skips what is already done)
set -euo pipefail
cd "$(dirname "$0")/.."
scripts/setup_host.sh
scripts/fetch_sources.sh
scripts/build_avm.sh
scripts/build_dav2d.sh arm64
scripts/build_dav1d.sh arm64
if command -v nasm >/dev/null; then scripts/build_dav1d.sh host; else NOASM=1 scripts/build_dav1d.sh host; fi
