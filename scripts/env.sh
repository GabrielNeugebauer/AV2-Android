# Shared settings for the setup and build scripts. Sourced, not run: `source scripts/env.sh`.
# Every value can be overridden from the environment, e.g. ANDROID_NDK=/opt/ndk scripts/build_dav2d.sh
NDK_PINNED=28.2.13676358
NDK_ROOT=${ANDROID_HOME:-$HOME/Android/Sdk}/ndk
if [ -z "${ANDROID_NDK:-}" ]; then
    if [ -d "$NDK_ROOT/$NDK_PINNED" ]; then
        ANDROID_NDK=$NDK_ROOT/$NDK_PINNED
    else
        ANDROID_NDK=$(find "$NDK_ROOT" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort -V | tail -1)
    fi
fi
ANDROID_API=${ANDROID_API:-29}
NDK_BIN=$ANDROID_NDK/toolchains/llvm/prebuilt/linux-x86_64/bin
MESON=${MESON:-.venv/bin/meson}
JOBS=${JOBS:-$(nproc)}
export ANDROID_NDK ANDROID_API NDK_BIN MESON JOBS
