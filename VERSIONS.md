# Pinned versions

| Component | Version | Notes |
|---|---|---|
| dav2d | `45609d9` (2026-10-26) | https://code.videolan.org/videolan/dav2d |
| dav2d-test-data | `ec53c12` | AVM v15.0.0 conformance streams |
| dav1d | `4e3ab21` (2026-10-28) | for the AV1 comparison |
| AVM (encoder) | `14f43e4 (2026-10-08)`, branch `av2-normative` | the branch dav2d's CI decodes against; built in `build/avm-x86` |
| Android NDK | 28.2.13676358 | target API 29 (Android 10), arm64-v8a |
| meson | 1.12.1 | in `.venv/` |

Builds (see `build/android-arm64.meson`):
- `build/dav2d-arm64`: release, default `trim_dsp`; the decoder used for benchmarks.
- `build/dav2d-arm64-checkasm`: release with `-Dtrim_dsp=false`, needed by checkasm.
