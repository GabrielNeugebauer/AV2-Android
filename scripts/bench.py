"""Benchmarks dav2d on an Android phone over adb and writes one CSV row per run.

For each stream: one decode with --verify checks the output against the reference MD5, then N timed runs
decode with the null muxer, one at a time, with a cool-down in between. Each timed run records the wall time
measured on the phone, the per-frame times from dav2d, the highest CPU temperature before and after, and the
average battery power during the run.

Usage (from the AV2-Android folder):
    python scripts/bench.py --serial e113b3850013 --streams streams/*.obu --runs 5 --threads 1 8 \
        --out results/bench.csv [--lock-clocks] [--battery-power] [--cpumask 0] [--freq 0:1017600] [--cpus 0-5]

Power is only meaningful with --battery-power: while the USB cable charges the phone, the battery current includes
the charging current. --battery-power pauses the USB input (root) so the phone runs on battery, keeping adb connected.

--freq pins a CPU cluster at one frequency (root) and --cpus keeps the decoder on chosen cores (taskset); together they
measure how decoding scales with clock speed on one core type. scripts/freq_sweep.sh runs that for every frequency.

The phone must already have dav2d in /data/local/tmp/av2 (scripts/phone_smoke_test.sh pushes it). Each stream needs a
<stream>.md5 next to it (scripts/make_streams.py writes it). The CSV columns are described in README.md.
"""

import argparse
import csv
import shlex
import signal
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PHONE_DIR = "/data/local/tmp/av2"
DAV2D = f"{PHONE_DIR}/dav2d"
CPUFREQ = "/sys/devices/system/cpu/cpufreq"
FIELDS = ["date", "device", "stream", "threads", "cpumask", "cpus", "clocks", "freq_khz", "power_source", "run", "frames", "wall_s", "fps",
          "frametime_median_ms", "frametime_max_ms", "temp_before_c", "temp_after_c", "power_mw", "md5_ok"]


def adb(serial, command, root=False, check=True):
    """Runs a shell command on the phone and returns its output. With root=True it runs through su (KernelSU)."""
    cmd = f"su -c {shlex.quote(command)}" if root else command
    res = subprocess.run(["adb", "-s", serial, "shell", "-n", cmd], capture_output=True, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"adb failed ({res.returncode}): {command}\n{res.stdout}{res.stderr}")
    return res.stdout.strip()


def max_cpu_temp(serial):
    """Highest of the CPU thermal zones, in °C."""
    out = adb(serial, "for z in /sys/class/thermal/thermal_zone*; do "
                      "case $(cat $z/type) in cpu-*) cat $z/temp;; esac; done")
    temps = [int(t) for t in out.split() if t.lstrip("-").isdigit()]
    return max(temps) / 1000 if temps else float("nan")


def cool_down(serial, target_c, timeout_s):
    """Waits until the CPU is below target_c, or until timeout_s has passed."""
    start = time.time()
    while max_cpu_temp(serial) > target_c and time.time() - start < timeout_s:
        time.sleep(5)


def set_clocks(serial, governor):
    """Sets the governor of every CPU policy (needs root). 'performance' pins the maximum frequency.

    The ROM on the Redmi keeps scaling_governor read-only (0444), so it is made writable for the change
    and read-only again afterwards."""
    adb(serial, f"for p in /sys/devices/system/cpu/cpufreq/policy*; do f=$p/scaling_governor; "
                f"chmod 644 $f; echo {governor} > $f; chmod 444 $f; done", root=True)


def read_limits(serial):
    """Frequency limits of every CPU policy, as {policy: (scaling_min_freq, scaling_max_freq)} in kHz."""
    out = adb(serial, f"for p in {CPUFREQ}/policy*; do "
                      f"echo ${{p##*policy}} $(cat $p/scaling_min_freq) $(cat $p/scaling_max_freq); done")
    return {int(a): (int(b), int(c)) for a, b, c in (line.split() for line in out.splitlines())}


def set_limits(serial, policy, low, high):
    """Sets one policy's frequency range (needs root). Min goes to the hardware minimum first, so min <= max
    holds at every step whichever way the range moves."""
    path = f"{CPUFREQ}/policy{policy}"
    adb(serial, f"cat {path}/cpuinfo_min_freq > {path}/scaling_min_freq; "
                f"echo {high} > {path}/scaling_max_freq; echo {low} > {path}/scaling_min_freq", root=True)


def current_freqs(serial):
    """Current frequency of every policy, as 'policy:kHz' pairs, e.g. '0:1017600 6:2304000'."""
    return " ".join(adb(serial, f"for p in {CPUFREQ}/policy*; do "
                                f"echo ${{p##*policy}}:$(cat $p/scaling_cur_freq); done").split())


def format_ranges(policies, ranges):
    """[(576000, 576000), (2304000, 2304000)] -> '0:576000 6:2304000'; a range shows as low-high."""
    return " ".join(f"{p}:{lo}" if lo == hi else f"{p}:{lo}-{hi}" for p, (lo, hi) in zip(policies, ranges))


def parse_freqs(serial, specs):
    """'0:1017600' -> {0: 1017600}, checked against the policy's available frequencies."""
    freqs = {}
    for spec in specs:
        policy, khz = (int(x) for x in spec.split(":"))
        available = adb(serial, f"cat {CPUFREQ}/policy{policy}/scaling_available_frequencies").split()
        if str(khz) not in available:
            raise SystemExit(f"policy{policy} has no {khz} kHz step; available: {' '.join(available)}")
        freqs[policy] = khz
    return freqs


def cpu_mask(cpus):
    """'0-5' or '6,7' -> hex affinity mask for taskset ('3f', 'c0')."""
    mask = 0
    for part in cpus.split(","):
        lo, _, hi = part.partition("-")
        for cpu in range(int(lo), int(hi or lo) + 1):
            mask |= 1 << cpu
    return f"{mask:x}"


def set_usb_input(serial, enabled):
    """Pauses or resumes charging from USB (needs root); adb keeps working."""
    adb(serial, f"echo {0 if enabled else 1} > /sys/class/power_supply/battery/input_suspend", root=True)


def push_if_needed(serial, local):
    """Copies a stream to the phone unless a file of the same size is already there. Returns its path on the phone."""
    remote = f"{PHONE_DIR}/streams/{local.name}"
    size = adb(serial, f"stat -c %s {remote} 2>/dev/null || echo 0")
    if int(size or 0) != local.stat().st_size:
        subprocess.run(["adb", "-s", serial, "push", str(local), remote], check=True, capture_output=True)
    return remote


def timed_run(serial, remote, threads, cpumask, cpus=None):
    """Decodes once with the null muxer. Returns wall time (s), per-frame times (ms), average power (mW) and the
    CPU frequencies seen during the decode, per policy in policy order, as (lowest, highest) kHz pairs."""
    mask = f"--cpumask {cpumask}" if cpumask is not None else ""
    pin = f"taskset {cpu_mask(cpus)} " if cpus else ""
    ft = f"{PHONE_DIR}/frametimes.txt"
    power = f"{PHONE_DIR}/power.txt"
    bat = "/sys/class/power_supply/battery"
    # Everything runs inside one shell on the phone, so adb latency is not part of the timing.
    # A background loop samples battery current (uA), voltage (uV) and the frequency of every CPU policy (kHz)
    # every 100 ms during the decode.
    # The sampler stops itself when the decode writes the "done" file, so no kill is needed.
    done = f"{PHONE_DIR}/done"
    script = (
        f"rm -f {ft} {power} {done}; "
        f"(while [ ! -e {done} ]; do echo $(cat {bat}/current_now) $(cat {bat}/voltage_now) "
        f"$(cat {CPUFREQ}/policy*/scaling_cur_freq) >> {power}; "
        f"sleep 0.1; done) & "
        f"t0=$(date +%s%N); "
        f"{pin}{DAV2D} -q -i {remote} --threads {threads} {mask} --muxer null -o /dev/null --frametimes {ft}; rc=$?; "
        f"t1=$(date +%s%N); touch {done}; wait; "
        f"echo WALL $((t1 - t0)) RC $rc; cat {ft}; echo POWER; cat {power}"
    )
    out = adb(serial, script)
    head, _, rest = out.partition("\n")
    parts = head.split()
    if parts[3] != "0":
        raise RuntimeError(f"dav2d failed on {remote}: rc={parts[3]}")
    wall_s = int(parts[1]) / 1e9
    frames_part, _, power_part = rest.partition("POWER")
    frametimes = [float(x) / 1e6 for x in frames_part.split()]  # dav2d writes the time between output frames in ns
    samples = [list(map(int, line.split())) for line in power_part.strip().splitlines()
               if len(line.split()) >= 2 and all(x.lstrip("-").isdigit() for x in line.split())]
    # current_now is negative while discharging on this phone; power = |I| * V
    power_mw = statistics.mean(abs(s[0]) * s[1] / 1e9 for s in samples) if samples else float("nan")
    freq_ranges = [(min(col), max(col)) for col in zip(*(s[2:] for s in samples))] if samples else []
    # (empty when the frequencies are not readable on this phone)
    return wall_s, frametimes, power_mw, freq_ranges


def main():
    # A stop signal (e.g. from a task runner) exits through the finally block, so the phone is restored.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(1))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--serial", required=True)
    ap.add_argument("--streams", nargs="+", type=Path, required=True,
                    help="AV2 .obu files; the expected MD5 is read from <stream>.md5")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--threads", type=int, nargs="+", default=[1])
    ap.add_argument("--cpumask", default=None, help="passed to dav2d --cpumask (0 = plain C only)")
    ap.add_argument("--lock-clocks", action="store_true", help="set the 'performance' governor during the runs (root)")
    ap.add_argument("--battery-power", action="store_true", help="pause USB charging during the runs (root)")
    ap.add_argument("--freq", nargs="+", metavar="POLICY:KHZ",
                    help="pin CPU policies at one frequency, e.g. 0:1017600 (root); other policies run at maximum")
    ap.add_argument("--cpus", help="run the decoder only on these cores, e.g. 0-5 (A55) or 6-7 (A76) on the Redmi")
    ap.add_argument("--cooldown-c", type=float, default=40.0, help="wait until the CPU is below this temperature")
    ap.add_argument("--cooldown-timeout", type=float, default=180.0)
    ap.add_argument("--pause", type=float, default=0.0,
                    help="fixed pause before each run, in seconds; use it on phones whose temperatures are not readable")
    ap.add_argument("--out", type=Path, default=Path("results/bench.csv"))
    opts = ap.parse_args()

    device = adb(opts.serial, "getprop ro.product.model")
    freqs = parse_freqs(opts.serial, opts.freq) if opts.freq else {}
    lock = opts.lock_clocks or bool(freqs)
    governor = adb(opts.serial, f"cat {CPUFREQ}/policy0/scaling_governor 2>/dev/null", check=False)
    clocks = "fixed" if freqs else "performance" if lock else governor or "unknown"  # unreadable without root on some phones
    opts.out.parent.mkdir(parents=True, exist_ok=True)
    new_file = not opts.out.exists()
    if not new_file:
        with open(opts.out) as f:
            if next(csv.reader(f), None) != FIELDS:
                raise SystemExit(f"{opts.out} has other columns (written by an older bench.py); use a new --out file")
    original_limits = read_limits(opts.serial) if freqs else {}
    # Policy numbers, in the same order as the policy* glob on the phone (single digits)
    policies = sorted(int(d.rsplit("policy", 1)[1]) for d in adb(opts.serial, f"ls -d {CPUFREQ}/policy*").split())

    power_source = "battery" if opts.battery_power else "usb"
    if lock:
        set_clocks(opts.serial, "performance")
    for policy, khz in freqs.items():
        set_limits(opts.serial, policy, khz, khz)
    if freqs:
        time.sleep(1)
        now = dict(pair.split(":") for pair in current_freqs(opts.serial).split())
        for policy, khz in freqs.items():
            if int(now[str(policy)]) != khz:
                print(f"Warning: policy{policy} runs at {now[str(policy)]} kHz, not {khz}", flush=True)
    if opts.battery_power:
        set_usb_input(opts.serial, enabled=False)
    try:
        with open(opts.out, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            if new_file:
                writer.writeheader()
            for stream in opts.streams:
                remote = push_if_needed(opts.serial, stream)
                md5 = stream.with_suffix(".md5").read_text().split()[0]
                md5_ok = adb(opts.serial, f"{DAV2D} -q -i {remote} --verify {md5}; echo $?", check=False).endswith("0")
                print(f"{stream.name}: MD5 {'OK' if md5_ok else 'MISMATCH'}", flush=True)
                for threads in opts.threads:
                    for run in range(1, opts.runs + 1):
                        cool_down(opts.serial, opts.cooldown_c, opts.cooldown_timeout)
                        time.sleep(opts.pause)
                        t_before = max_cpu_temp(opts.serial)
                        wall_s, frametimes, power_mw, ranges = timed_run(opts.serial, remote, threads, opts.cpumask,
                                                                          opts.cpus)
                        freq_seen = format_ranges(policies, ranges) if ranges else current_freqs(opts.serial)
                        moved = [f"policy{p}" for p, (lo, hi) in zip(policies, ranges)
                                 if p in freqs and not lo == hi == freqs[p]]
                        t_after = max_cpu_temp(opts.serial)
                        row = {
                            "date": datetime.now().isoformat(timespec="seconds"),
                            "device": device, "stream": stream.name, "threads": threads,
                            "cpumask": opts.cpumask if opts.cpumask is not None else "all",
                            "cpus": opts.cpus or "all", "clocks": clocks, "freq_khz": freq_seen,
                            "power_source": power_source,
                            "run": run, "frames": len(frametimes), "wall_s": round(wall_s, 4),
                            "fps": round(len(frametimes) / wall_s, 3),
                            "frametime_median_ms": round(statistics.median(frametimes), 3),
                            "frametime_max_ms": round(max(frametimes), 3),
                            "temp_before_c": t_before, "temp_after_c": t_after,
                            "power_mw": round(power_mw, 1), "md5_ok": md5_ok,
                        }
                        writer.writerow(row)
                        f.flush()
                        print(f"  threads={threads} run={run}: {row['fps']} fps, "
                              f"{t_before:.1f}->{t_after:.1f} °C, {row['power_mw']} mW", flush=True)
                        if moved:
                            print(f"    Warning: {', '.join(moved)} left the fixed frequency during this run "
                                  f"({freq_seen}); the power HAL or thermal service overrode it", flush=True)
    finally:
        if opts.battery_power:
            set_usb_input(opts.serial, enabled=True)
        for policy, (low, high) in original_limits.items():
            set_limits(opts.serial, policy, low, high)
        if lock:
            set_clocks(opts.serial, "schedutil")


if __name__ == "__main__":
    main()
