# AV2 software decoding on Android

Measures how well Android phones without AV2 hardware decode AV2 in software with [dav2d](https://code.videolan.org/videolan/dav2d), and later speeds it up with NEON code (and, optionally, the GPU or DSP). The plan is in `proposal.html` / `AV2 Mobile Decoding Proposal.docx`; the task list is `TODO.md`; pinned versions are in `VERSIONS.md`.

```
PC                                                       phone (adb)
scripts/bootstrap.sh → src/ (pinned clones) → build/ (dav2d, dav1d, AVM)
  scripts/install_phone.py ──────────────────────────────→ /data/local/tmp/av2/{dav2d,dav1d,checkasm*}
  scripts/device_info.py  ←──────────────────────────────── props, CPU clusters, thermal, power, codecs, GPU
       → devices/<codename>/summary.md
reference_videos/*.y4m
  ├─ scripts/make_streams.py      (AVM encoder + reference decoder)
  └─ scripts/make_av1_streams.py  (libaom / SVT-AV1 + dav1d MD5)
       → streams/<set>/*.obu|*.ivf + *.md5 ──────────────→ /data/local/tmp/av2/streams/
                                                          dav2d / dav1d decodes, checks MD5, is timed
  scripts/bench.py  ←──────────────────────────────────── times, temperatures, power
       → results/*.csv
  scripts/summarize.py → table per decoder / stream / threads / code path
```

## Folder layout

| Path                                       | Content                                                                                                                            |
| ------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| `src/`                                     | Clones: `dav2d`, `dav2d-test-data` (AVM v15 conformance streams), `dav1d` (for the AV1 comparison), `avm` (branch `av2-normative`) |
| `build/android-arm64.meson`, `-armv7.meson` | Meson cross files for the Android NDK (API 29), written by `scripts/make_cross_file.sh`                                           |
| `build/dav2d-<arch>/`, `build/dav1d-<arch>/` | Decoders for the phone (`arm64`, `armv7`), release builds: the decoders used for benchmarks (`tools/dav2d`, `tools/dav1d`)       |
| `build/<decoder>-<arch>-checkasm/`         | Same, with `-Dtrim_dsp=false`, needed by checkasm (`tests/checkasm`)                                                               |
| `build/dav1d-x86/`                         | dav1d for the PC: reference MD5s of AV1 streams                                                                                    |
| `build/avm-x86/`                           | AVM encoder and decoder for the PC, optimized and multithreaded (`avmenc`, `avmdec`)                                               |
| `build/avm/`                               | AVM built without `AVM_TARGET_CPU`: plain C, single-threaded, many times slower. Not used                                          |
| `devices/`                                 | One folder per phone from `scripts/device_info.py`: raw adb outputs and `summary.md` / `summary.json`                              |
| `reference_videos/`                        | Source sequences (`.y4m`)                                                                                                          |
| `streams/`                                 | Encoded test streams, one folder per set: AV2 `.obu` or AV1 `.ivf`, each with its `.md5` and `.enc.log`                            |
| `results/`                                 | Benchmark CSVs                                                                                                                     |
| `scripts/`                                 | The scripts below; `interativo.py` holds the menus they share                                                                      |
| `tools_html2docx.py`                       | Regenerates the proposal `.docx` from `proposal.html`                                                                              |
| `.venv/`                                   | Python environment with meson, created by `scripts/setup_host.sh`                                                                  |

## Phone requirements

- USB debugging on, `adb devices` lists the phone. The scripts list the connected phones and ask which one to use (`e113b3850013` is the Redmi Note 12 Pro 4G, `SM02G4061988026` the Seeker).
- Run `scripts/device_info.py` once per phone: its `summary.md` says what the phone allows (root, readable temperatures and clocks, battery files, 32-bit only) and what to answer in `bench.py`.
- Nothing needs root to decode: binaries and streams live in `/data/local/tmp/av2`.
- Without root (the Seeker) the runner still checks MD5s and records times and the frequencies seen, but cannot lock clocks, pause charging or read temperatures; power readings are taken while charging and are not meaningful. Core numbering differs per phone: Redmi 0-5 A55 / 6-7 A76; Seeker 0-3 A55 / 4-7 A78.
- The governor, fixed-frequency and battery questions of `bench.py` need root over adb; without it the script skips them. With KernelSU, allow **Shell** under Superuser; check with `adb shell su -c id`.

## Setting up from scratch

On a new PC, `scripts/bootstrap.sh` runs every step below in order. Each step skips what is already done, so it is also safe to run again. The scripts work from any folder; relative paths are taken from the AV2-Android folder.

| Step | Script | What it does |
| ---- | ------ | ------------ |
| 1 | `scripts/setup_host.sh` | Checks git, cmake, make, ninja, ffmpeg, adb, python3, nasm (optional) and the NDK, printing `OK` or `MISSING` with the install command. Creates `.venv` with meson 1.12.1. Installs nothing system-wide; exits 1 if a required tool is missing |
| 2 | `scripts/fetch_sources.sh [name...]` | Clones `dav2d`, `dav2d-test-data`, `dav1d`, `avm` (branch `av2-normative`) and `libaom` (`v3.15.3`) into `src/` and checks out the pinned commits. Clones that are already at their pin are left alone; one at another commit is moved to the pin only if it has no local changes |
| 3 | `scripts/build_avm.sh` | AVM encoder and reference decoder for the PC (`build/avm-x86/avmenc`, `avmdec`), optimized and multithreaded |
| 3b | `scripts/build_libaom.sh` | libaom AV1 encoder and decoder for the PC (`build/libaom-x86/aomenc`, `aomdec`), used by `Scripts-ViTech/AVM/run_avm.py` for the CTC v9 AV1 encodes |
| 4 | `scripts/build_dav2d.sh [arm64\|armv7]` | dav2d for the phone: the release decoder and the checkasm build. Run in a terminal without an argument, it asks for the architecture |
| 5 | `scripts/build_dav1d.sh [arm64\|armv7\|host]` | dav1d (AV1, for the comparison) for the phone in the same layout, or `host` for the PC, to compute the reference MD5 of AV1 streams. Without an argument, it asks |

`scripts/env.sh` holds the shared settings and the build scripts source it. `scripts/make_cross_file.sh <arm64|armv7> <out.meson>` writes the meson cross file from those settings (`build/android-arm64.meson`, `build/android-armv7.meson`). The build scripts call it themselves, and it only rewrites the file when the content changes, so ninja does not reconfigure the builds for nothing.

The pinned commits are kept in one place, at the top of `fetch_sources.sh`. To move to a newer upstream commit, change the pin there and in `VERSIONS.md`, then run the script and the builds again.

### Settings

| Variable | Default | Used by |
| -------- | ------- | ------- |
| `ANDROID_NDK` | `$ANDROID_HOME/ndk/28.2.13676358` (or `~/Android/Sdk/ndk/...`) if present, otherwise the newest NDK there | cross files |
| `ANDROID_API` | 29 (Android 10) | cross files: the minimum Android version the binaries run on |
| `MESON` | `.venv/bin/meson` | dav2d and dav1d builds |
| `JOBS` | `nproc` | all builds |
| `RECONFIGURE` | unset | `=1`: re-run `meson setup --reconfigure` on existing build folders (after changing the NDK or API) |
| `NOASM` | unset | `build_dav1d.sh host` only: `=1` builds plain C without nasm (same output, slower, no checkasm) |
| `SRC_DIR` | `src` | `fetch_sources.sh`: clone somewhere else |
| `BUILD_DIR` | `build/avm-x86` | `build_avm.sh` |
| `CONFIGURE_ONLY` | unset | `build_avm.sh`: `=1` runs cmake only |

If the NDK is missing: `sdkmanager --sdk_root=$HOME/Android/Sdk 'ndk;28.2.13676358'`.

### Build outputs

| Folder | Content |
| ------ | ------- |
| `build/dav2d-arm64/` | dav2d release build for the phone; `tools/dav2d` is the decoder used for benchmarks |
| `build/dav2d-arm64-checkasm/` | `-Dtrim_dsp=false`, for `tests/checkasm` |
| `build/dav2d-armv7/`, `build/dav2d-armv7-checkasm/` | The same for 32-bit-only phones. dav2d has arm32 NEON for MC, CDEF, intra prediction, film grain and the entropy decoder (fewer functions than arm64: no inverse transforms or loop restoration) |
| `build/dav1d-arm64/`, `build/dav1d-arm64-checkasm/` | dav1d for the phone: `tools/dav1d`, `tests/checkasm` |
| `build/dav1d-armv7/`, `build/dav1d-armv7-checkasm/` | The same, 32-bit |
| `build/dav1d-x86/` | dav1d for the PC (`tools/dav1d`): reference MD5s of AV1 streams |
| `build/avm-x86/` | `avmenc`, `avmdec` for the PC |

### Traps

- **AVM builds plain C without `AVM_TARGET_CPU`.** The `av2-normative` branch silently builds generic, single-threaded C unless `-DAVM_TARGET_CPU=x86_64` is set, which makes it many times slower (`build/avm/` is such a build and is not used). `build_avm.sh` sets it.
- **`-DENABLE_EXAMPLES=0` also drops `avmenc` and `avmdec`.** Leave it out. The AVM build also compiles TensorFlow Lite, so the first build takes several minutes.
- **checkasm needs `-Dtrim_dsp=false`.** Release builds remove the plain C reference functions that checkasm compares against, so the decoder and checkasm are two separate build folders.
- **dav1d on the PC needs nasm for its assembly.** Without nasm the script stops with the install hint. `NOASM=1` builds plain C instead. The decoded output is identical, so it is fine for reference MD5s, but checkasm is then skipped because its own x86 file still needs nasm (`yasm` alone does not assemble it).
- **Compare MD5s in the stream's own pixel format.** dav1d's `--muxer md5` hashes the decoded planes as they are. An ffmpeg check must decode to the same format the stream has (`yuv420p` or `yuv420p10le` for the project's streams, which is what `make_av1_streams.py` does); converting to another format gives a different hash.

## Scripts

The scripts that need choices are interactive, in the same pattern as the Scripts-ViTech runners: run them with no arguments (`.venv/bin/python scripts/<name>.py` or `python3 scripts/<name>.py`, from any folder) and they ask in the terminal, in Portuguese, with numbered menus. Selections accept lists and ranges (`1,2,3` or `1-3,5`), and a blank answer takes the default shown in the prompt. Each one shows a summary and asks `Iniciar? [s/N]` before it changes anything. Ctrl+C cancels.

Questions shared by several scripts:

- **Celular:** the phones in `adb devices` (model and serial). After the choice the script prints the manufacturer, model, Android version, SoC and ABIs.
- **Fontes / streams:** the `.y4m` files under `reference_videos/`, or the stream files under `streams/` that have a `.md5` next to them.

### `scripts/device_info.py`

Records a phone's specifications over adb, in one pass, for the device table of the article and to choose the `bench.py` answers for that phone. It works without root. When `adb shell su -c id` returns root, it also reads cpufreq, thermal zones and the DSP folders as root (`*.root.txt`). It only reads: it changes no setting on the phone.

It asks for the phone and the output folder (default `devices`). The phone's folder is named after `ro.product.device` (its codename), e.g. `devices/sweet2/` for the Redmi and `devices/seeker/` for the Seeker. The raw outputs go to `<folder>/<codename>/raw/`. At the end it runs `device_summary.py`, which writes `summary.md` and `summary.json` next to them. Run the script again to refresh a phone; it overwrites the folder's files.

| File in `raw/`                            | Content                                                                                                                                                        |
| ----------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `collected.txt`                           | Serial, date, whether root works, SELinux mode                                                                                                                 |
| `props.txt`                               | Model, manufacturer, codename, Android version and SDK, fingerprint, ABI lists, SoC properties, EGL/Vulkan hints                                               |
| `uname.txt`, `meminfo.txt`, `battery.txt` | Kernel, `/proc/meminfo`, `dumpsys battery` (level, status, temperature)                                                                                        |
| `cpuinfo.txt`, `cpus.txt`                 | `/proc/cpuinfo`; per core `midr_el1` and online state                                                                                                          |
| `cpufreq.txt` (`.root.txt`)               | Per policy: related CPUs, hardware and current limits, frequency steps, governors, or `unreadable`                                                             |
| `thermal.txt` (`.root.txt`)               | Every thermal zone: type and temperature, or `unreadable`                                                                                                      |
| `power.txt`                               | Power supplies; for each battery file `bench.py` uses (and other charge-pause files): exists, readable, writable, mode, value; 5 samples of status and current |
| `codecs.xml.txt`                          | Every `media_codecs*.xml` (vendor, odm, system, product, swcodec APEX) that lists a `video/av0*` codec                                                         |
| `gpu.txt`, `features.txt`, `vkjson.json`  | GLES renderer from SurfaceFlinger, Vulkan driver libraries, `pm list features`, `cmd gpu vkjson`                                                               |
| `dsp.txt` (`.root.txt`)                   | FastRPC device nodes, DSP libraries in `public.libraries.txt`, `/vendor/dsp`; with root, the `fastrpc_shell*` files                                            |

`summary.md` is a table with what the project needs to know about the phone:

| Row                  | How it is read                                                                                                                                                                                                                                          |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ABIs                 | `ro.product.cpu.abilist`; flags 32-bit-only phones, where the arm64 build does not run                                                                                                                                                                  |
| `policyN`            | One row per CPU cluster: cores, core type (CPU implementer and part, Qualcomm Kryo parts named after their Arm core), frequency range and steps, governor, and the `--cpumask` extensions all its cores have (`neon`, `dotprod`, `i8mm`, `sve`, `sve2`) |
| Frequencies readable | Whether `scaling_cur_freq` (used for the `freq_khz` column) and the min/max limits can be read without root                                                                                                                                             |
| Thermal zones        | How many zones are readable and how many are `cpu-*`, the zones `bench.py` uses for the cool-down; with none, the cool-down cannot work                                                                                                                 |
| Battery sysfs        | Whether `current_now`, `voltage_now` and `input_suspend` exist; sign of `current_now` while charging or discharging, and whether it looks like µA or mA                                                                                                 |
| AV1 decoders         | AV1 decoders in the codec lists; a decoder whose name does not start with `c2.android.`, `c2.google.` or `OMX.google.` counts as hardware                                                                                                               |
| AV2 codecs           | Any codec of another `video/av0*` type                                                                                                                                                                                                                  |
| GPU, DSP             | GLES renderer, Vulkan version (from `vkjson`, else from the `android.hardware.vulkan.version` feature), FastRPC nodes, `libcdsprpc`, and with root whether `fastrpc_shell_unsigned_3` exists                                                            |

It ends with suggested answers to the `bench.py` questions (cores per cluster, cool-down temperature or a fixed pause, the root-only choices, the `--cpumask` values) and the frequency steps of each policy. `summary.json` holds the same fields for the analysis scripts.

`scripts/device_summary.py` can be run on its own to rebuild a summary from the raw files, for example after a change to the parser. It lists the phone folders under `devices/` and `results/`.

Notes:

- The codec lists come from the XML files. They show what the system registers; an app's `MediaCodecList` can still differ on some ROMs.
- `current_now` is µA on most phones; the summary flags values that look like mA. The sign while charging is only known if the phone was charging (or discharging) while the script ran.
- `devices/` is small text and meant to be tracked in git, so the specifications of each phone stay with the results. The summary contains the adb serial.

### `scripts/install_phone.py`

Copies the decoders and their checkasm builds to `/data/local/tmp/av2` on the phone and records what is installed. Run it after every rebuild; `phone_smoke_test.py` and `bench.py` use what it installs.

It asks for the phone, the architecture (default from the phone's `ro.product.cpu.abilist`: `arm64` if it lists `arm64-v8a`, else `armv7`), the decoders (each shows its source commit, or its build script if it is not built; blank = every built one) and whether to install checkasm.

| Built on the PC                          | On the phone (`/data/local/tmp/av2/`) |
| ---------------------------------------- | ------------------------------------- |
| `build/dav2d-<arch>/tools/dav2d`         | `dav2d`                               |
| `build/dav2d-<arch>-checkasm/tests/checkasm` | `checkasm`                        |
| `build/dav1d-<arch>/tools/dav1d`         | `dav1d`                               |
| `build/dav1d-<arch>-checkasm/tests/checkasm` | `checkasm-dav1d`                  |

- Each pushed file is made executable and its SHA-256 on the phone is compared with the local file. A missing checkasm build is reported but does not stop the install.
- It ends by printing `--version` of each installed decoder, run on the phone, and the phone's `VERSIONS` file: one line per decoder with its source commit (from `src/<decoder>`, `-dirty` if the clone has local changes), arch and install date. Installing one decoder keeps the other's line.

```
dav1d 4e3ab21 arm64 2026-10-31T16:19:00-03:00
dav2d 45609d9 arm64 2026-10-31T16:19:00-03:00
```

`Scripts-ViTech/Android/install_decoders.py` installs the same files in the same layout and also copies the test streams, `VERSIONS` and a report to the phone's Downloads folder.

### `scripts/phone_smoke_test.py`

Checks that the decoders work on a phone. It asks the same questions as `install_phone.py` (phone, architecture, decoders) and, for dav1d, which folder of AV1 streams to check (folders under `streams/` with `.ivf` files that have a `.md5`). Then it installs the decoders and tests each one:

- **dav2d**: pushes the `dav2d-test-data` streams, decodes each one and compares it with its reference MD5 (from the test-data meson file), then runs checkasm. Expected on the Redmi and the Seeker: 10 of 10 streams pass and `checkasm: all 1714 tests passed`.
- **dav1d**: runs `checkasm-dav1d` (2545 tests on the Redmi), then decodes the chosen folder's `.ivf` streams with `--verify`. With no AV1 streams it only runs checkasm.

Failed streams print `FAIL <name>`; read the `Streams:` lines.

### `scripts/make_streams.py`

Encodes AV2 test streams on the PC and writes each one's reference MD5.

| Question     | Default   | Meaning                                                                                                                      |
| ------------ | --------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Fontes       |           | `.y4m` sources under `reference_videos/`; the smallest are encoded first                                                     |
| Bit depth    | 10        | 10, 8 or both                                                                                                                |
| QPs          | 160       | AVM qindex values, comma-separated (up to 255; higher = lower bitrate)                                                       |
| Frames       | 33        | Frames to encode                                                                                                             |
| `--cpu-used` | 0         | Encoder speed preset, 0–9. The CTC uses 0; 9 is the fastest but uses fewer coding tools, so streams may be lighter to decode |
| Threads      | 8         | Encoder threads (only with `build/avm-x86`)                                                                                  |
| Pasta        | `streams` | Output folder                                                                                                                |

For each source, bit depth and QP it:

1. converts the source to 8 bit with ffmpeg if 8 bit is asked (once, kept in the output folder);
2. encodes the first frames with `avmenc`, using the random-access settings of `Scripts-ViTech/AVM/cfg/av2/random_access.cfg`;
3. decodes the stream with `avmdec --md5 --rawvideo` (the reference decoder) and saves the MD5 next to it.

Output names: `<video>_<height>p_<bits>bit_qp<QP>_f<frames>_s<preset>.obu`, plus `.md5` and `.enc.log`. The script uses `build/avm-x86` when it exists, else `build/avm`.

### `scripts/make_av1_streams.py`

Encodes AV1 test streams on the PC, for the AV1 vs. AV2 comparison (RQ2), and writes each one's reference MD5. It is the AV1 counterpart of `make_streams.py` and uses the system ffmpeg's `libaom-av1` and `libsvtav1` encoders. (For the CTC v9 AV1 encodes with `aomenc`, use `Scripts-ViTech/AVM/run_avm.py`.)

| Question | Default   | Meaning                                                                                            |
| -------- | --------- | -------------------------------------------------------------------------------------------------- |
| Fontes   |           | `.y4m` sources under `reference_videos/`; the smallest are encoded first                           |
| Encoder  | SVT-AV1   | SVT-AV1 or libaom                                                                                  |
| Bit depth| 10        | 10, 8 or both                                                                                      |
| QPs      | 40        | AV1 QPs, 0–63, comma-separated (higher = lower bitrate)                                            |
| Frames   | 33        | Frames to encode                                                                                   |
| Preset   | 2 / 0     | Speed preset: SVT-AV1 preset 0–13 (default 2), libaom `cpu-used` 0–8 (default 0). Higher is faster |
| Threads  | 8         | Encoder threads (libaom `-threads` with row multithreading; SVT-AV1 `lp`)                          |
| PSNR     | no        | Append stream, encoder, QP, bit depth, frames, kbps, PSNR Y and PSNR YUV to `<out>/quality.csv`    |
| Pasta    | `streams` | Output folder                                                                                      |

For each source, bit depth and QP it:

1. converts the source to 8 bit with ffmpeg if 8 bit is asked (the same file and conversion as `make_streams.py`, so AV1 and AV2 encode the same pixels when both use the same output folder);
2. encodes the first frames at a fixed QP, with a GOP close to `Scripts-ViTech/AVM/cfg/av2/random_access.cfg`: 16-frame mini-GOP, key frame every 65 frames, no TPL, no adaptive quantization;
3. decodes the stream and saves the MD5 next to it, in the form `dav1d --verify` checks on the phone;
4. if asked, measures the decoded stream against its source and appends a row to `<out>/quality.csv`.

Output names: `<video>_<height>p_<bits>bit_<encoder>_q<QP>_f<frames>_p<preset>.ivf`, plus `.md5` and `.enc.log`. The log starts with the full ffmpeg command, followed by ffmpeg's banner and the encoder version. Each stream prints its size, bitrate (kbps, from the file size and the source frame rate) and, if asked, its PSNR.

**Rate control.** The AVM config encodes with a fixed QP per frame (`--end-usage=q --use-fixed-qp-offsets=1`, no TPL, no delta-q). The closest match in each encoder:

- **SVT-AV1:** `-qp <QP>` with `aq-mode=0` is CQP: a fixed QP per pyramid level, and SVT disables TPL with it. `hierarchical-levels=4` gives the 16-frame mini-GOP. The log confirms it (`BRC mode / CQP Assignment : CQP / <QP>`, `gop size / mini-gop size : 65 / 16`).
- **libaom:** `-crf <QP> -b:v 0` is constant-quality mode (`end-usage=q`), with `aq-mode=0`, `deltaq-mode=0`, `enable-tpl-model=0`, `min/max-gf-interval=16`, `gf-min/max-pyr-height=4`, `lag-in-frames=19` and `enable-keyframe-filtering=0`, as in the AVM config. libaom 3.8 does not take `use-fixed-qp-offsets` through ffmpeg, so the QP offsets per pyramid level are libaom's own.

AV1 QPs (0–63) and AVM QPs (0–255) are on different scales; compare operating points by bitrate and PSNR (`quality.csv`), not by QP.

**MD5.** The MD5 must equal dav1d's md5 muxer (what `dav1d --verify` checks on the phone). The script uses `build/dav1d-x86/tools/dav1d --muxer md5` when that host build exists; otherwise it hashes the decoded frames with ffmpeg (`-c:v libdav1d -f md5`, `yuv420p` or `yuv420p10le`). Both give the same hash: all 8 test streams (both encoders, 8 and 10 bit, two QPs) matched a host dav1d's md5 muxer, and passed `dav1d --verify`.

### `scripts/bench.py`

Benchmarks dav2d (or dav1d) on the phone. For each stream it copies the stream to the phone if needed, decodes it once with `--verify` to check the MD5, then makes the timed decodes for each thread count, one at a time. Before each timed run it waits until the CPU cools below the chosen temperature (at most 180 s).

The timing runs in a single shell on the phone, so adb latency is not included. Each run decodes with the null muxer (no output written), records the decoder's per-frame times (`--frametimes`), and samples the battery current and voltage every 100 ms.

| Question            | Default             | Meaning                                                                                                                                                         |
| ------------------- | ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Celular             |                     | The phone                                                                                                                                                       |
| Decodificador       | dav2d               | `dav2d` for AV2 `.obu` streams, `dav1d` for AV1 `.ivf` streams. It must be installed with `install_phone.py`; the script stops if it is not                     |
| Streams             |                     | Files under `streams/` of that type with a `.md5` next to them                                                                                                  |
| Threads             | 1                   | One or more decoder thread counts, comma-separated                                                                                                              |
| Execuções           | 5                   | Timed runs per stream and thread count                                                                                                                          |
| Código              | all                 | `--cpumask`: every optimization, `0` = plain C only (measures the NEON gain), `neon`, `dotprod`, `i8mm`                                                         |
| Núcleos             | all                 | Runs the decoder only on one cluster's cores (`taskset`), listed from the phone, e.g. 0-5 (A55) or 6-7 (A76) on the Redmi                                         |
| Bateria             | yes (root)          | Pauses USB charging during the runs, so the power figures are real. adb stays connected                                                                         |
| Frequência          | none (root)         | Pins one cluster at one of its frequency steps, chosen from the list the phone reports; other clusters run at maximum. The original limits are restored at the end. Implies the `performance` governor |
| Governor            | no (root)           | Sets the `performance` governor during the runs. The Redmi's ROM keeps the setting read-only, so the script unlocks it for the change and locks it again       |
| Temperatura         | 40 °C               | Target CPU temperature between runs. With locked clocks the Redmi idles at 50–55 °C: use about 58. On phones whose temperatures cannot be read (the Seeker without root) it asks for a fixed pause in seconds instead |
| CSV                 | `results/bench.csv` | Output file; new runs are appended                                                                                                                              |

Without root it skips the battery, frequency and governor questions and says so; power readings then include the charging current.

Charging and the governor are restored at the end, also when the script fails or is stopped. If the PC loses the phone mid-run, restore them by hand:

```bash
adb shell "su -c 'echo 0 > /sys/class/power_supply/battery/input_suspend; for p in /sys/devices/system/cpu/cpufreq/policy*; do f=\$p/scaling_governor; chmod 644 \$f; echo schedutil > \$f; chmod 444 \$f; done'"
```

CSV columns:

| Column                                    | Meaning                                                                                |
| ----------------------------------------- | -------------------------------------------------------------------------------------- |
| `date`, `device`                          | When the run finished; phone model                                                     |
| `decoder`                                 | `dav2d` or `dav1d`                                                                     |
| `stream`, `threads`, `cpumask`, `cpus`    | What was decoded and how (`all` = every optimization, every core)                      |
| `clocks`, `power_source`                  | Governor during the run (`fixed` with a fixed frequency); `battery` or `usb`                    |
| `freq_khz`                                | Frequency of each policy seen during the decode (`policy:kHz`; `low-high` if it moved) |
| `run`                                     | Run number                                                                             |
| `frames`, `wall_s`, `fps`                 | Frames decoded, wall time on the phone (s), frames per second                          |
| `frametime_median_ms`, `frametime_max_ms` | From dav2d's time between output frames                                                |
| `temp_before_c`, `temp_after_c`           | Highest CPU temperature before and after                                               |
| `power_mw`                                | Average battery power during the run; only meaningful when `power_source` is `battery` |
| `md5_ok`                                  | Whether the verified decode of this stream matched the reference                       |

Both decoders take the same command-line options that `bench.py` uses (`-q`, `--threads`, `--cpumask 0|neon|dotprod|i8mm`, `--muxer null`, `--frametimes`, `--verify`), so the code, threads and cores choices work the same way with either one. (Only `--inloopfilters` takes different values: dav1d has `nodeblock`, `nocdef`, `restoration`, `norestoration`; dav2d has `ccso`, `wiener`, `gdf` and `+`/`-` combinations.)

Older CSVs: a file written before this column existed (e.g. `results/poc_seeker.csv`) still takes new dav2d runs, in its own columns, since all its rows are dav2d; the script prints a note when it does this. dav1d runs into such a file are refused: choose another output CSV. `results/poc.csv` is older still (no `cpus`/`freq_khz`) and was already refused by the previous `bench.py`.

### `scripts/freq_sweep.py`

Runs `bench.py` once for every frequency step of one CPU cluster, with the decoder kept on that cluster's cores and the phone on battery. It shows how decoding speed and energy per frame scale with clock speed on one core type, which lets results from one phone predict others with the same cores at other clocks. It needs root.

It asks for the phone, the decoder and streams (as `bench.py`), the cluster (e.g. policy0 = A55 cores 0-5, 10 steps, and policy6 = A76 cores 6-7, 14 steps, on the Redmi), the frequencies (blank = all), the threads, the runs (default 5), the cool-down temperature (default 58 °C, at most 30 s per run) and the CSV (default `results/sweep_policy<N>.csv`).

On the Redmi, the ROM's power service (`libperfmgr`) briefly raises minimum frequencies on some events, and `thermal-engine` can lower the maximum when the phone is hot. `bench.py` records the frequencies during every decode (`freq_khz`) and warns when a fixed frequency moved; discard or repeat those runs.

### `scripts/summarize.py`

Lists the CSVs under `results/` (most recent first) and prints median, minimum and maximum fps and median power for each decoder, stream, thread count and code path of the chosen one. Rows of older CSVs without a `decoder` column count as dav2d.

### `tools_html2docx.py <html> <docx>`

Converts `proposal.html` into the `.docx` sent to the supervisor (headings, paragraphs, lists, tables, links and inline code). Edit the page, then regenerate the file.

## Reproducing the proof of concept

```bash
scripts/bootstrap.sh
.venv/bin/python scripts/make_streams.py        # SparksElevator; 10 and 8 bit; QP 210; 17 frames; cpu-used 9; streams/poc
.venv/bin/python scripts/phone_smoke_test.py
.venv/bin/python scripts/bench.py               # streams/poc; threads 1,8; 5 runs; battery; governor performance; 58 °C
.venv/bin/python scripts/bench.py               # the same with code "C puro (--cpumask 0)" and 1 thread
.venv/bin/python scripts/summarize.py
```

These streams are tiny (about 0.1 s of decoding), so they only show that the pipeline works. Real measurements need at least 1–2 s of decoding per run. The `results/poc.csv` in the folder was written by an older `bench.py` with fewer columns; to reproduce, write to a new file.
