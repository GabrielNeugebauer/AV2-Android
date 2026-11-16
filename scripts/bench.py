"""Benchmarks dav2d (or dav1d, for the AV1 comparison) on an Android phone over adb and writes one CSV row per run.

For each stream: one decode with --verify checks the output against the reference MD5, then N timed runs
decode with the null muxer, one at a time, with a cool-down in between. Each timed run records the wall time
measured on the phone, the per-frame times from the decoder, the highest CPU temperature before and after, and the
average battery power during the run.

Interactive: python3 scripts/bench.py
It asks for the phone, the decoder, the streams (files under streams/ with a .md5 next to them, written by
make_streams.py or make_av1_streams.py), the threads, the number of runs, the code path (--cpumask), the cores
(taskset), and, with root, battery power, a fixed frequency for one CPU cluster and the governor.

Power is only meaningful on battery: while the USB cable charges the phone, the battery current includes the charging
current. Running on battery pauses the USB input (root) and keeps adb connected. scripts/freq_sweep.py runs this
for every frequency of one cluster.

The phone must already have the decoder in /data/local/tmp/av2 (scripts/install_phone.py pushes it). The CSV columns
are described in README.md. CSVs written before the decoder column existed are still appended to, in their own
columns, when the decoder is dav2d (all their rows are dav2d); dav1d runs need a CSV with the decoder column.
"""

import csv
import os
import shlex
import signal
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from interativo import (ROOT, adb_shell, ask_number, ask_numbers, ask_text, ask_yes, choose_phone,
                        confirm_or_exit, has_root, menu, pick_files, title)

PHONE_DIR = "/data/local/tmp/av2"
CPUFREQ = "/sys/devices/system/cpu/cpufreq"
FIELDS = ["date", "device", "decoder", "stream", "threads", "cpumask", "cpus", "clocks", "freq_khz", "power_source", "run", "frames", "wall_s", "fps",
          "frametime_median_ms", "frametime_max_ms", "temp_before_c", "temp_after_c", "power_mw", "md5_ok"]
OLD_FIELDS = [f for f in FIELDS if f != "decoder"]  # CSVs from before --decoder; all their rows are dav2d


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


def timed_run(serial, decoder, remote, threads, cpumask, cpus=None):
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
        f"{pin}{PHONE_DIR}/{decoder} -q -i {remote} --threads {threads} {mask} --muxer null -o /dev/null --frametimes {ft}; rc=$?; "
        f"t1=$(date +%s%N); touch {done}; wait; "
        f"echo WALL $((t1 - t0)) RC $rc; cat {ft}; echo POWER; cat {power}"
    )
    out = adb(serial, script)
    head, _, rest = out.partition("\n")
    parts = head.split()
    if parts[3] != "0":
        raise RuntimeError(f"{decoder} failed on {remote}: rc={parts[3]}")
    wall_s = int(parts[1]) / 1e9
    frames_part, _, power_part = rest.partition("POWER")
    frametimes = [float(x) / 1e6 for x in frames_part.split()]  # the decoder writes the time between output frames in ns
    samples = [list(map(int, line.split())) for line in power_part.strip().splitlines()
               if len(line.split()) >= 2 and all(x.lstrip("-").isdigit() for x in line.split())]
    # current_now is negative while discharging on this phone; power = |I| * V
    power_mw = statistics.mean(abs(s[0]) * s[1] / 1e9 for s in samples) if samples else float("nan")
    freq_ranges = [(min(col), max(col)) for col in zip(*(s[2:] for s in samples))] if samples else []
    # (empty when the frequencies are not readable on this phone)
    return wall_s, frametimes, power_mw, freq_ranges


def read_policies(serial):
    """CPU clusters: {policy: (cores as '0,1,2', [available frequencies in kHz])}; the list is empty if unreadable."""
    out = adb(serial, f"for p in {CPUFREQ}/policy*; do echo \"${{p##*policy}}|$(cat $p/related_cpus)|"
                      f"$(cat $p/scaling_available_frequencies 2>/dev/null)\"; done", check=False)
    policies = {}
    for line in out.splitlines():
        policy, cpus, freqs = (line.split("|") + ["", ""])[:3]
        if policy.isdigit():
            policies[int(policy)] = (",".join(cpus.split()), [int(f) for f in freqs.split() if f.isdigit()])
    return dict(sorted(policies.items()))


def cores_label(cpus):
    """'0,1,2,3,4,5' -> '0-5' when the cores are consecutive."""
    ids = [int(c) for c in cpus.split(",")]
    return f"{ids[0]}-{ids[-1]}" if len(ids) > 1 and ids == list(range(ids[0], ids[-1] + 1)) else cpus


def choose_decoder_and_streams(serial):
    decoder = ["dav2d", "dav1d"][menu("DECODIFICADOR", ["dav2d (AV2, streams .obu)", "dav1d (AV1, streams .ivf)"],
                                      "Selecione (em branco = 1): ", default=0)]
    if adb_shell(serial, f"test -x {PHONE_DIR}/{decoder}")[0] != 0:
        raise SystemExit(f"{PHONE_DIR}/{decoder} não está no celular: rode python3 scripts/install_phone.py")
    streams = pick_files("STREAMS (com .md5)", ROOT / "streams", {".obu"} if decoder == "dav2d" else {".ivf"},
                         need_md5=True)
    return decoder, streams


def ask_cooldown(serial):
    """(target °C, pause s): cool down to a temperature, or a fixed pause when the temperature is unreadable."""
    temp = max_cpu_temp(serial)
    if temp == temp:  # not NaN
        return ask_number(f"Esfriar até quantos °C antes de cada execução (agora {temp:.1f} °C)", 40.0, float), 0.0
    print("A temperatura da CPU não é legível neste celular; use uma pausa fixa entre as execuções.")
    return 40.0, ask_number("Pausa antes de cada execução, em segundos", 10.0, float, minimum=0)


def ask_options():
    serial = choose_phone()
    decoder, streams = choose_decoder_and_streams(serial)
    title("EXECUÇÃO")
    threads = ask_numbers("Threads do decodificador", [1])
    runs = ask_number("Execuções por stream e número de threads", 5, minimum=1)
    cpumask = [None, "0", "neon", "dotprod", "i8mm"][menu("CÓDIGO (--cpumask)", [
        "Todas as otimizações (assembly)", "C puro (--cpumask 0)", "Até NEON (--cpumask neon)",
        "Até dotprod (--cpumask dotprod)", "Até i8mm (--cpumask i8mm)"], "Selecione (em branco = 1): ", default=0)]
    policies = read_policies(serial)
    rows = ["Todos os núcleos"] + [f"Núcleos {cores_label(c)} (policy{p})" for p, (c, _) in policies.items()]
    sel = menu("NÚCLEOS (taskset)", rows, "Selecione (em branco = 1): ", default=0)
    cpus = list(policies.values())[sel - 1][0] if sel else None

    freqs, lock, battery = {}, False, False
    if has_root(serial):
        battery = ask_yes("\nRodar na bateria (pausa a carga pela USB, para medir a potência)? [S/n]: ", default=True)
        fixable = [p for p, (_, f) in policies.items() if f]
        sel = menu("FREQUÊNCIA", ["Não fixar"] + [f"Fixar a policy{p} (núcleos {cores_label(policies[p][0])})"
                                                  for p in fixable], "Selecione (em branco = 1): ", default=0)
        if sel:
            policy = fixable[sel - 1]
            steps = policies[policy][1]
            khz = steps[menu(f"FREQUÊNCIA DA policy{policy}", [f"{f / 1000:.0f} MHz ({f} kHz)" for f in steps],
                             "Selecione: ")]
            freqs = {policy: khz}
        lock = bool(freqs) or ask_yes("Fixar o governor em 'performance' durante as execuções? [s/N]: ")
    else:
        print("\nSem root: governor, frequência e carga pela USB ficam como estão (a potência inclui a carga).")
    cooldown, pause = ask_cooldown(serial)
    out = Path(ask_text("Arquivo CSV de saída", "results/bench.csv"))
    return SimpleNamespace(serial=serial, decoder=decoder, streams=streams, runs=runs, threads=threads,
                           cpumask=cpumask, lock_clocks=lock, battery_power=battery, freqs=freqs, cpus=cpus,
                           cooldown_c=cooldown, cooldown_timeout=180.0, pause=pause, out=out)


def describe(opts):
    title("RESUMO")
    print(f"{opts.decoder}, {len(opts.streams)} stream(s), threads {opts.threads}, {opts.runs} execuções")
    print(f"código: {opts.cpumask or 'todas as otimizações'}; núcleos: {cores_label(opts.cpus) if opts.cpus else 'todos'}; "
          f"frequência: {', '.join(f'policy{p} {k} kHz' for p, k in opts.freqs.items()) or 'livre'}; "
          f"bateria: {'sim' if opts.battery_power else 'não'}")
    print(f"saída: {opts.out}")


def run(opts):
    """Runs the benchmark described by opts (see ask_options) and appends the rows to opts.out."""
    device = adb(opts.serial, "getprop ro.product.model")
    freqs = opts.freqs
    lock = opts.lock_clocks or bool(freqs)
    governor = adb(opts.serial, f"cat {CPUFREQ}/policy0/scaling_governor 2>/dev/null", check=False)
    clocks = "fixed" if freqs else "performance" if lock else governor or "unknown"  # unreadable without root on some phones
    opts.out.parent.mkdir(parents=True, exist_ok=True)
    new_file = not opts.out.exists()
    fields = FIELDS
    if not new_file:
        with open(opts.out) as f:
            header = next(csv.reader(f), None)
        if header == OLD_FIELDS:
            if opts.decoder != "dav2d":
                raise SystemExit(f"{opts.out} has no decoder column (older bench.py, dav2d only); "
                                 f"choose another output CSV for {opts.decoder}")
            fields = OLD_FIELDS
            print(f"{opts.out} has no decoder column (older bench.py); appending in its columns", flush=True)
        elif header != FIELDS:
            raise SystemExit(f"{opts.out} has other columns (written by an older bench.py); choose another output CSV")
    binary = f"{PHONE_DIR}/{opts.decoder}"
    if adb(opts.serial, f"test -x {binary} && echo yes", check=False) != "yes":
        raise SystemExit(f"{binary} is not on the phone; run python3 scripts/install_phone.py")
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
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            if new_file:
                writer.writeheader()
            for stream in opts.streams:
                remote = push_if_needed(opts.serial, stream)
                md5 = stream.with_suffix(".md5").read_text().split()[0]
                md5_ok = adb(opts.serial, f"{binary} -q -i {remote} --verify {md5}; echo $?", check=False).split()[-1] == "0"
                print(f"{stream.name}: MD5 {'OK' if md5_ok else 'MISMATCH'}", flush=True)
                for threads in opts.threads:
                    for run in range(1, opts.runs + 1):
                        cool_down(opts.serial, opts.cooldown_c, opts.cooldown_timeout)
                        time.sleep(opts.pause)
                        t_before = max_cpu_temp(opts.serial)
                        wall_s, frametimes, power_mw, ranges = timed_run(opts.serial, opts.decoder, remote, threads,
                                                                          opts.cpumask, opts.cpus)
                        freq_seen = format_ranges(policies, ranges) if ranges else current_freqs(opts.serial)
                        moved = [f"policy{p}" for p, (lo, hi) in zip(policies, ranges)
                                 if p in freqs and not lo == hi == freqs[p]]
                        t_after = max_cpu_temp(opts.serial)
                        row = {
                            "date": datetime.now().isoformat(timespec="seconds"),
                            "device": device, "decoder": opts.decoder, "stream": stream.name, "threads": threads,
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



def main():
    # A stop signal (e.g. from a task runner) exits through the finally block, so the phone is restored.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(1))
    os.chdir(ROOT)
    opts = ask_options()
    describe(opts)
    confirm_or_exit()
    run(opts)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nCancelado.")
