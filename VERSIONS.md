# Pinned versions

| Component | Version | Notes |
|---|---|---|
| dav2d | `45609d9` (2026-10-26) | https://code.videolan.org/videolan/dav2d |
| dav2d-test-data | `ec53c12` | AVM v15.0.0 conformance streams |
| dav1d | `4e3ab21` (2026-10-28) | for the AV1 comparison |
| AVM (encoder) | `14f43e4 (2026-10-08)`, branch `av2-normative` | the branch dav2d's CI decodes against; built in `build/avm-x86` |
| libaom (aomenc/aomdec) | `v3.15.3` (`b141d9c`) | standard AV1 encoder for the CTC v9 encodes (`Scripts-ViTech/AVM/run_avm.py`); built in `build/libaom-x86` |
| Android NDK | 28.2.13676358 | target API 29 (Android 10), arm64-v8a |
| meson | 1.12.1 | in `.venv/` (`scripts/setup_host.sh`) |
| ffmpeg | 6.1.1-3ubuntu5 (system) | runs the AV1 encoders in `make_av1_streams.py` |
| libaom | 3.8.2 (Ubuntu `libaom3` 3.8.2-2ubuntu0.2) | AV1 encoder, `--encoder libaom` |
| SVT-AV1 | 1.7.0 (Ubuntu `libsvtav1enc1d1` 1.7.0+dfsg-2build1) | AV1 encoder, `--encoder svtav1` |
| Host tools | cmake 3.28.3, ninja 1.11.1, GNU Make 4.3, adb 1.0.41, Python 3.12.3 | nasm not installed |

The source pins are also at the top of `scripts/fetch_sources.sh`; change both together.

Builds (cross files written by `scripts/make_cross_file.sh` from `scripts/env.sh`: NDK 28.2.13676358, API 29):
- `build/dav2d-arm64`: release, default `trim_dsp`; the decoder used for benchmarks.
- `build/dav2d-arm64-checkasm`: release with `-Dtrim_dsp=false`, needed by checkasm.
- `build/dav2d-armv7`, `build/dav2d-armv7-checkasm`: the same for 32-bit phones (arm32 NEON for MC, CDEF, intra, film grain, entropy decoder; no transforms or loop restoration).
- `build/dav1d-arm64`, `build/dav1d-arm64-checkasm`, `build/dav1d-armv7`, `build/dav1d-armv7-checkasm`: dav1d with the same options.
- `build/dav1d-x86`: dav1d for the PC, release, `NOASM=1` (plain C, no checkasm) because nasm is not installed; used for AV1 reference MD5s.
