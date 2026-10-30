# AV2 software decoding on Android

Measures how well Android phones without AV2 hardware decode AV2 in software with [dav2d](https://code.videolan.org/videolan/dav2d), and later speeds it up with NEON code (and, optionally, the GPU or DSP). The plan is in `proposal.html` / `AV2 Mobile Decoding Proposal.docx`; the task list is `TODO.md`; pinned versions are in `VERSIONS.md`.

```
PC                                                       phone (adb)
reference_videos/*.y4m
  └─ scripts/make_streams.py  (AVM encoder + reference decoder)
       → streams/<set>/*.obu + *.md5 ─────────────────→ /data/local/tmp/av2/streams/
                                                          dav2d decodes, checks MD5, is timed
  scripts/bench.py  ←──────────────────────────────────── times, temperatures, power
       → results/*.csv
  scripts/summarize.py → table per stream / threads / code path
```

## Folder layout

| Path                          | Content                                                                                                                            |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `src/`                        | Clones: `dav2d`, `dav2d-test-data` (AVM v15 conformance streams), `dav1d` (for the AV1 comparison), `avm` (branch `av2-normative`) |
| `build/android-arm64.meson`   | Meson cross file for the Android NDK (arm64, API 29)                                                                               |
| `build/dav2d-arm64/`          | dav2d for the phone, release build: the decoder used for benchmarks (`tools/dav2d`)                                                |
| `build/dav2d-arm64-checkasm/` | Same, with `-Dtrim_dsp=false`, needed by checkasm (`tests/checkasm`)                                                               |
| `build/avm-x86/`              | AVM encoder and decoder for the PC, optimized and multithreaded (`avmenc`, `avmdec`)                                               |
| `build/avm/`                  | AVM built without `AVM_TARGET_CPU`: plain C, single-threaded, many times slower. Not used                                          |
| `reference_videos/`           | Source sequences (`.y4m`)                                                                                                          |
| `streams/`                    | Encoded AV2 test streams, one folder per set, each `.obu` with its `.md5` and `.enc.log`                                           |
| `results/`                    | Benchmark CSVs                                                                                                                     |
| `scripts/`                    | The scripts below                                                                                                                  |
| `tools_html2docx.py`          | Regenerates the proposal `.docx` from `proposal.html`                                                                              |
| `.venv/`                      | Python environment with meson (`python3 -m venv .venv && .venv/bin/pip install meson`)                                             |

## Phone requirements

- USB debugging on, `adb devices` lists the phone. Pass its serial to the scripts (`e113b3850013` for the Redmi Note 12 Pro 4G).
- Nothing needs root to decode: binaries and streams live in `/data/local/tmp/av2`.
- Without root (the Seeker) the runner still checks MD5s and records times and the frequencies seen, but cannot lock clocks, pause charging or read temperatures; power readings are taken while charging and are not meaningful. Core numbering differs per phone: Redmi 0-5 A55 / 6-7 A76; Seeker 0-3 A55 / 4-7 A78.
- `--lock-clocks`, `--battery-power` and `--freq` need root over adb. With KernelSU, allow **Shell** under Superuser; check with `adb shell su -c id`.

## Building

### dav2d for the phone

```bash
.venv/bin/meson setup build/dav2d-arm64 src/dav2d --cross-file build/android-arm64.meson \
    --buildtype release -Ddefault_library=static -Denable_tools=true -Denable_tests=true -Dtestdata_tests=false
ninja -C build/dav2d-arm64

# checkasm needs the plain C reference functions, which release builds remove
.venv/bin/meson setup build/dav2d-arm64-checkasm src/dav2d --cross-file build/android-arm64.meson \
    --buildtype release -Ddefault_library=static -Denable_tools=false -Denable_tests=true -Dtrim_dsp=false
ninja -C build/dav2d-arm64-checkasm tests/checkasm
```

`build/android-arm64.meson` points at the NDK in `~/Android/Sdk/ndk/28.2.13676358`; edit the paths if the NDK moves. API 29 (Android 10) lets the same binary run on all the test phones.

### AVM for the PC

```bash
mkdir -p build/avm-x86 && cd build/avm-x86
cmake ../../src/avm -DCMAKE_BUILD_TYPE=Release -DAVM_TARGET_CPU=x86_64 -DCONFIG_MULTITHREAD=1 \
    -DENABLE_TESTS=0 -DENABLE_DOCS=0
make -j8 avmenc avmdec
```

Two traps: the `av2-normative` branch builds plain C unless `AVM_TARGET_CPU` is set, and `-DENABLE_EXAMPLES=0` also drops `avmenc` and `avmdec`. The build also compiles TensorFlow Lite, so it takes several minutes.

## Scripts

### `scripts/phone_smoke_test.sh <serial>`

Checks that dav2d works on a phone. It pushes dav2d, checkasm and the `dav2d-test-data` streams to `/data/local/tmp/av2`, decodes every stream and compares it with its reference MD5, then runs checkasm. Expected result on the Redmi: 10 of 10 streams pass and `checkasm: all 1714 tests passed`. Run it again after rebuilding dav2d.

### `scripts/make_streams.py`

Encodes AV2 test streams on the PC and writes each one's reference MD5.

For each input, bit depth and QP it:

1. converts the source to 8 bit with ffmpeg if `--bitdepth 8` is asked (once, kept in the output folder);
2. encodes the first `--frames` frames with `avmenc`, using the random-access settings of `Scripts-ViTech/AVM/cfg/random_access.cfg`;
3. decodes the stream with `avmdec --md5 --rawvideo` (the reference decoder) and saves the MD5 next to it.

| Option       | Default   | Meaning                                                                                                                      |
| ------------ | --------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `inputs`     |           | One or more `.y4m` sources                                                                                                   |
| `--qp`       | 160       | One or more QPs (AV2 range up to 255; higher = lower bitrate)                                                                |
| `--frames`   | 33        | Frames to encode                                                                                                             |
| `--bitdepth` | 10        | 10 and/or 8                                                                                                                  |
| `--cpu-used` | 0         | Encoder speed preset, 0–9. The CTC uses 0; 9 is the fastest but uses fewer coding tools, so streams may be lighter to decode |
| `--threads`  | 8         | Encoder threads (only with `build/avm-x86`)                                                                                  |
| `--out`      | `streams` | Output folder                                                                                                                |

Output names: `<video>_<height>p_<bits>bit_qp<QP>_f<frames>_s<preset>.obu`, plus `.md5` and `.enc.log`. The script uses `build/avm-x86` when it exists, else `build/avm`.

### `scripts/bench.py`

Benchmarks dav2d on the phone. For each stream it copies the stream to the phone if needed, decodes it once with `--verify` to check the MD5, then makes `--runs` timed decodes for each thread count, one at a time. Before each timed run it waits until the CPU cools below `--cooldown-c` (or `--cooldown-timeout` passes).

The timing runs in a single shell on the phone, so adb latency is not included. Each run decodes with the null muxer (no output written), records dav2d's per-frame times (`--frametimes`), and samples the battery current and voltage every 100 ms.

| Option               | Default             | Meaning                                                                                                                                                         |
| -------------------- | ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--serial`           |                     | adb serial of the phone                                                                                                                                         |
| `--streams`          |                     | `.obu` files; each needs its `.md5`                                                                                                                             |
| `--runs`             | 5                   | Timed runs per stream and thread count                                                                                                                          |
| `--threads`          | 1                   | One or more dav2d thread counts                                                                                                                                 |
| `--cpumask`          | all                 | Passed to dav2d: `0` = plain C only (measures the NEON gain), `neon`, `dotprod`, `i8mm`                                                                         |
| `--lock-clocks`      | off                 | Sets the `performance` governor during the runs (root). The Redmi's ROM keeps the setting read-only, so the script unlocks it for the change and locks it again |
| `--freq`             | off                 | Pins CPU policies at one frequency each, as `POLICY:KHZ` (e.g. `0:1017600`; root). It must be one of the policy's steps; other policies run at maximum. The original limits are restored at the end. Implies `--lock-clocks` |
| `--cpus`             | all                 | Runs the decoder only on these cores (`taskset`), e.g. `0-5` (A55) or `6-7` (A76) on the Redmi |
| `--battery-power`    | off                 | Pauses USB charging during the runs (root), so the power figures are real. adb stays connected                                                                  |
| `--cooldown-c`       | 40                  | Target CPU temperature between runs. With locked clocks the Redmi idles at 50–55 °C: use about 58                                                               |
| `--cooldown-timeout` | 180                 | Maximum wait per run, in seconds                                                                                                                                |
| `--pause`            | 0                   | Fixed pause before each run, in seconds. For phones whose temperatures cannot be read without root (the Seeker), where the cool-down cannot work |
| `--out`              | `results/bench.csv` | CSV file; new runs are appended                                                                                                                                 |

Charging and the governor are restored at the end, also when the script fails or is stopped. If the PC loses the phone mid-run, restore them by hand:

```bash
adb shell "su -c 'echo 0 > /sys/class/power_supply/battery/input_suspend; for p in /sys/devices/system/cpu/cpufreq/policy*; do f=\$p/scaling_governor; chmod 644 \$f; echo schedutil > \$f; chmod 444 \$f; done'"
```

CSV columns:

| Column                                    | Meaning                                                                                |
| ----------------------------------------- | -------------------------------------------------------------------------------------- |
| `date`, `device`                          | When the run finished; phone model                                                     |
| `stream`, `threads`, `cpumask`, `cpus`    | What was decoded and how (`all` = every optimization, every core)                      |
| `clocks`, `power_source`                  | Governor during the run (`fixed` with `--freq`); `battery` or `usb`                    |
| `freq_khz`                                | Frequency of each policy seen during the decode (`policy:kHz`; `low-high` if it moved) |
| `run`                                     | Run number                                                                             |
| `frames`, `wall_s`, `fps`                 | Frames decoded, wall time on the phone (s), frames per second                          |
| `frametime_median_ms`, `frametime_max_ms` | From dav2d's time between output frames                                                |
| `temp_before_c`, `temp_after_c`           | Highest CPU temperature before and after                                               |
| `power_mw`                                | Average battery power during the run; only meaningful when `power_source` is `battery` |
| `md5_ok`                                  | Whether the verified decode of this stream matched the reference                       |

### `scripts/freq_sweep.sh <serial> <policy> <cpus> <threads> <out.csv> <stream.obu>...`

Runs `bench.py` once for every frequency step of one CPU cluster, with the decoder kept on that cluster's cores and the phone on battery. It shows how decoding speed and energy per frame scale with clock speed on one core type, which lets results from one phone predict others with the same cores at other clocks.

```bash
scripts/freq_sweep.sh e113b3850013 0 0-5 1 results/sweep_a55.csv streams/<set>/*.obu   # A55 cluster, 10 steps
scripts/freq_sweep.sh e113b3850013 6 6-7 1 results/sweep_a76.csv streams/<set>/*.obu   # A76 cluster, 14 steps
```

Environment variables: `RUNS` (default 5), `COOLDOWN_C` (default 58), `FREQS` to sweep only some steps (e.g. `FREQS="576000 1804800"`).

On the Redmi, the ROM's power service (`libperfmgr`) briefly raises minimum frequencies on some events, and `thermal-engine` can lower the maximum when the phone is hot. `bench.py` records the frequencies during every decode (`freq_khz`) and warns when a fixed frequency moved; discard or repeat those runs.

### `scripts/summarize.py <csv>`

Prints median, minimum and maximum fps and median power for each stream, thread count and code path in a bench CSV.

### `tools_html2docx.py <html> <docx>`

Converts `proposal.html` into the `.docx` sent to the supervisor (headings, paragraphs, lists, tables, links and inline code). Edit the page, then regenerate the file.

## Reproducing the proof of concept

```bash
.venv/bin/python scripts/make_streams.py reference_videos/SparksElevator_480x270p_5994_10bit.y4m \
    --qp 210 --frames 17 --bitdepth 10 8 --cpu-used 9 --out streams/poc
scripts/phone_smoke_test.sh e113b3850013
.venv/bin/python scripts/bench.py --serial e113b3850013 --streams streams/poc/*.obu --runs 5 --threads 1 8 \
    --lock-clocks --battery-power --cooldown-c 58 --cooldown-timeout 30 --out results/poc.csv
.venv/bin/python scripts/bench.py --serial e113b3850013 --streams streams/poc/*.obu --runs 5 --threads 1 \
    --cpumask 0 --lock-clocks --battery-power --cooldown-c 58 --cooldown-timeout 30 --out results/poc.csv
.venv/bin/python scripts/summarize.py results/poc.csv
```

These streams are tiny (about 0.1 s of decoding), so they only show that the pipeline works. Real measurements need at least 1–2 s of decoding per run.
