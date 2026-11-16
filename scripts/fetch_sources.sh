#!/usr/bin/env bash
# Clones the decoder and encoder sources into src/ and checks out the pinned commits (VERSIONS.md).
# Usage: scripts/fetch_sources.sh [name...]   (default: all; SRC_DIR=<dir> clones elsewhere)
# Existing clones at the pinned commit are left alone; one at another commit is moved to the pin only if it has no
# local changes. To move to a new upstream commit, change the pin here and in VERSIONS.md.
set -euo pipefail
cd "$(dirname "$0")/.."
SRC_DIR=${SRC_DIR:-src}
#      folder           url                                                    commit   branch
PINS="dav2d             https://code.videolan.org/videolan/dav2d.git           45609d9  main
      dav2d-test-data   https://code.videolan.org/videolan/dav2d-test-data.git ec53c12  main
      dav1d             https://code.videolan.org/videolan/dav1d.git           4e3ab21  master
      avm               https://github.com/AOMediaCodec/avm                    14f43e4  av2-normative
      libaom            https://aomedia.googlesource.com/aom                   b141d9c  v3.15.3"

mkdir -p "$SRC_DIR"
while read -r name url commit branch; do
    if [ $# -gt 0 ] && [[ " $* " != *" $name "* ]]; then continue; fi
    dir=$SRC_DIR/$name
    if [ ! -d "$dir/.git" ]; then
        echo "== cloning $name ($branch)"
        git clone --branch "$branch" --filter=blob:none "$url" "$dir"
    fi
    if [ "$(git -C "$dir" rev-parse HEAD)" = "$(git -C "$dir" rev-parse --verify -q "$commit^{commit}" || true)" ]; then
        echo "$name: at $commit"
        continue
    fi
    if [ -n "$(git -C "$dir" status --porcelain --untracked-files=no)" ]; then
        echo "$name: has local changes, not moving it to $commit" >&2
        exit 1
    fi
    git -C "$dir" cat-file -e "$commit^{commit}" 2>/dev/null || git -C "$dir" fetch origin "$branch"
    git -C "$dir" -c advice.detachedHead=false checkout -q "$commit"
    echo "$name: checked out $commit"
done <<< "$PINS"
