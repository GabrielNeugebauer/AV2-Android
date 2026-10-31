"""Turns the raw files written by scripts/device_info.sh into summary.md and summary.json.

The summary answers what the benchmark needs to know about a phone: which cores it has and how they are grouped,
what bench.py can read or set without root, whether it already has an AV1 hardware decoder, and which GPU and DSP
the offload work could use. It ends with suggested bench.py options.

Usage (from the AV2-Android folder):
    python3 scripts/device_summary.py devices/sweet2
"""

import json
import re
import sys
from pathlib import Path

# (implementer, part) from MIDR_EL1 / /proc/cpuinfo. Qualcomm Kryo parts are named after the Arm core they are based on.
CORES = {
    (0x41, 0xc07): "Cortex-A7", (0x41, 0xc09): "Cortex-A9", (0x41, 0xc0f): "Cortex-A15", (0x41, 0xc0e): "Cortex-A17",
    (0x41, 0xd03): "Cortex-A53", (0x41, 0xd04): "Cortex-A35", (0x41, 0xd05): "Cortex-A55", (0x41, 0xd06): "Cortex-A65",
    (0x41, 0xd07): "Cortex-A57", (0x41, 0xd08): "Cortex-A72", (0x41, 0xd09): "Cortex-A73", (0x41, 0xd0a): "Cortex-A75",
    (0x41, 0xd0b): "Cortex-A76", (0x41, 0xd0d): "Cortex-A77", (0x41, 0xd41): "Cortex-A78", (0x41, 0xd44): "Cortex-X1",
    (0x41, 0xd46): "Cortex-A510", (0x41, 0xd47): "Cortex-A710", (0x41, 0xd48): "Cortex-X2", (0x41, 0xd4b): "Cortex-A78C",
    (0x41, 0xd4d): "Cortex-A715", (0x41, 0xd4e): "Cortex-X3", (0x41, 0xd80): "Cortex-A520", (0x41, 0xd81): "Cortex-A720",
    (0x41, 0xd82): "Cortex-X4", (0x41, 0xd85): "Cortex-X925", (0x41, 0xd87): "Cortex-A725",
    (0x51, 0x800): "Kryo 2xx Gold (A73)", (0x51, 0x801): "Kryo 2xx Silver (A53)",
    (0x51, 0x802): "Kryo 3xx Gold (A75)", (0x51, 0x803): "Kryo 3xx Silver (A55)",
    (0x51, 0x804): "Kryo 4xx Gold (A76)", (0x51, 0x805): "Kryo 4xx Silver (A55)", (0x51, 0x001): "Oryon",
}
# /proc/cpuinfo feature flag -> name used by dav2d/dav1d --cpumask (where one exists)
FEATURES = {"asimd": "neon", "neon": "neon", "asimddp": "dotprod", "i8mm": "i8mm", "sve": "sve", "sve2": "sve2",
            "bf16": "bf16", "asimdhp": "fp16"}


def read(d, name):
    p = d / "raw" / name
    return p.read_text(errors="replace") if p.exists() else ""


def core_name(impl, part):
    return CORES.get((impl, part), f"unknown (0x{impl:02x}/0x{part:03x})")


def ranges(cpus):
    """[0, 1, 2, 3, 6, 7] -> '0-3,6-7'"""
    spans = []
    for c in sorted(cpus):
        if spans and c == spans[-1][1] + 1:
            spans[-1][1] = c
        else:
            spans.append([c, c])
    return ",".join(str(a) if a == b else f"{a}-{b}" for a, b in spans)


def parse_cores(d):
    """Per CPU: core name and feature flags, from /proc/cpuinfo, with midr_el1 as fallback."""
    cores = {}
    for block in read(d, "cpuinfo.txt").split("\n\n"):
        f = dict((k.strip().lower(), v.strip()) for k, _, v in (l.partition(":") for l in block.splitlines()) if _)
        if "processor" in f and f["processor"].isdigit() and "cpu part" in f:
            cores[int(f["processor"])] = {"name": core_name(int(f["cpu implementer"], 16), int(f["cpu part"], 16)),
                                          "features": f.get("features", "").split()}
    for line in read(d, "cpus.txt").splitlines():
        m = re.match(r"cpu(\d+) (0x[0-9a-f]+)", line)
        if m and int(m[1]) not in cores:
            midr = int(m[2], 16)
            cores[int(m[1])] = {"name": core_name((midr >> 24) & 0xff, (midr >> 4) & 0xfff), "features": []}
    return cores


def parse_policies(text):
    pol = {}
    for line in text.splitlines():
        m = re.match(r"policy(\d+) (\S+) ?(.*)", line)
        if m:
            pol.setdefault(int(m[1]), {})[m[2]] = m[3].strip()
    return pol


def readable(v):
    return v is not None and v != "unreadable" and v != ""


def parse_clusters(d, cores):
    shell = parse_policies(read(d, "cpufreq.txt"))
    root = parse_policies(read(d, "cpufreq.root.txt"))
    ncpu = max(cores) + 1 if cores else 0
    nums = sorted(shell)
    clusters = []
    for i, n in enumerate(nums):
        s, r = shell[n], root.get(n, {})
        get = lambda k: s.get(k) if readable(s.get(k)) else r.get(k) if readable(r.get(k)) else None  # noqa: E731
        rel = get("related_cpus")
        cpus = [int(c) for c in rel.split()] if rel else list(range(n, nums[i + 1] if i + 1 < len(nums) else ncpu))
        freqs = sorted(int(f) for f in (get("scaling_available_frequencies") or "").split())
        names = sorted({cores[c]["name"] for c in cpus if c in cores})
        feats = set.intersection(*(set(cores[c]["features"]) for c in cpus if c in cores)) if names else set()
        lo = get("cpuinfo_min_freq") or (str(freqs[0]) if freqs else None)
        hi = get("cpuinfo_max_freq") or (str(freqs[-1]) if freqs else None)
        clusters.append({
            "policy": n, "cpus": ranges(cpus), "count": len(cpus), "core": " + ".join(names) or "unknown",
            "min_khz": int(lo) if lo else None, "max_khz": int(hi) if hi else None, "freqs_khz": freqs,
            "governor": s.get("scaling_governor") if readable(s.get("scaling_governor")) else "unreadable",
            "governor_root": r.get("scaling_governor"),
            "governors_available": (get("scaling_available_governors") or "").split(),
            "cur_freq_readable": readable(s.get("scaling_cur_freq")),
            "limits_readable": readable(s.get("scaling_min_freq")) and readable(s.get("scaling_max_freq")),
            "cpumask_features": sorted({FEATURES[f] for f in feats if f in FEATURES}),
        })
    return clusters


def parse_thermal(text):
    zones = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0].startswith("thermal_zone"):
            temp = parts[-1]
            zones.append({"zone": parts[0], "type": " ".join(parts[1:-1]),
                          "temp_c": int(temp) / 1000 if temp.lstrip("-").isdigit() else None})
    cpu = [z for z in zones if z["type"].startswith("cpu-") and z["temp_c"] is not None]
    return {"zones": len(zones), "readable": sum(z["temp_c"] is not None for z in zones),
            "cpu_zones_readable": len(cpu), "cpu_max_c": max((z["temp_c"] for z in cpu), default=None)}


def parse_power(d):
    files, samples = {}, []
    for line in read(d, "power.txt").splitlines():
        if line.startswith("file "):
            name, *kv = line[5:].split(" ")
            f = dict(x.split("=", 1) for x in kv if "=" in x)
            files[name] = {"exists": f.get("exists") == "1", "readable": f.get("r") == "1", "writable": f.get("w") == "1",
                           "mode": f.get("mode"), "value": " ".join([f.get("value", "")] + [x for x in kv if "=" not in x])}
        elif line.startswith("sample "):
            m = re.match(r"sample (.*?) (-?\d+) (\d+)$", line)
            if m:
                samples.append((m[1], int(m[2])))
    charging = [i for st, i in samples if st.lower() == "charging"]
    discharging = [i for st, i in samples if st.lower() == "discharging"]
    sign = ("positive while charging" if charging and min(charging) > 0 else
            "negative while charging" if charging and max(charging) < 0 else
            "negative while discharging" if discharging and max(discharging) < 0 else
            "positive while discharging" if discharging and min(discharging) > 0 else "unknown")
    mags = [abs(i) for _, i in samples if i]
    unit = None if not mags else "mA (small values)" if max(mags) < 20000 else "uA"
    ok = lambda n: files.get(n, {}).get("readable", False)  # noqa: E731
    return {"current_now": ok("current_now"), "voltage_now": ok("voltage_now"),
            "input_suspend": files.get("input_suspend", {}).get("exists", False),
            "charge_controls": [n for n in ("input_suspend", "charging_enabled", "battery_charging_enabled",
                                            "charge_disable") if files.get(n, {}).get("exists")],
            "current_sign": sign, "current_unit": unit, "status": samples[0][0] if samples else None}


def parse_codecs(text):
    codecs = {}
    for m in re.finditer(r"<MediaCodec\b([^>]*)>(.*?)(?:</MediaCodec>|(?=<MediaCodec\b))|<MediaCodec\b([^>]*)/>",
                         text, re.S):
        attrs = m[1] or m[3] or ""
        name = re.search(r'name="([^"]+)"', attrs)
        if not name:
            continue
        types = re.findall(r'type="([^"]+)"', attrs) + re.findall(r'<Type\s+name="([^"]+)"', m[2] or "")
        for t in types:
            if t.lower().startswith("video/av0"):
                n = name[1]
                sw = n.startswith(("c2.android.", "OMX.google.", "c2.google."))
                codecs[n] = {"type": t.lower(), "encoder": "encoder" in n.lower(), "software": sw}
    return codecs


def parse_gpu(d):
    gles = next((l[5:].strip() for l in read(d, "gpu.txt").splitlines() if l.startswith("gles ")), "")
    gles = gles.removeprefix("GLES:").strip()
    feats = dict(l.removeprefix("feature:").split("=", 1) for l in read(d, "features.txt").splitlines()
                 if l.startswith("feature:") and "=" in l)
    vk = feats.get("android.hardware.vulkan.version")
    vk = f"{int(vk) >> 22}.{(int(vk) >> 12) & 0x3ff}" if vk and vk.isdigit() else None
    vk_device, vk_api = None, None
    try:
        dev = json.loads(read(d, "vkjson.json"))["devices"][0]["properties"]
        v = int(dev["apiVersion"])
        vk_device, vk_api = dev["deviceName"], f"{v >> 22}.{(v >> 12) & 0x3ff}.{v & 0xfff}"
    except (ValueError, KeyError, IndexError, TypeError):
        pass
    return {"gles": gles or None, "vulkan": vk_api or vk, "vulkan_device": vk_device}


def parse_dsp(d):
    text = read(d, "dsp.txt")
    section = text.partition("## nodes")[2].partition("##")[0]
    nodes = sorted(l.split()[-1] for l in section.splitlines() if re.match(r"[bcl-][rwxsS-]{9}", l))
    public = text.partition("## public libs")[2].partition("##")[0]
    root = read(d, "dsp.root.txt")
    shells = re.findall(r"\S*fastrpc_shell\w*", root.partition("## fastrpc shells")[2])
    return {"fastrpc_nodes": nodes, "cdsp_lib": "libcdsprpc.so" in public,
            "unsigned_pd_shell": (any("fastrpc_shell_unsigned_3" in s for s in shells) if root else None),
            "fastrpc_shells": shells}


def summarize(d):
    props = dict(l.split("=", 1) for l in read(d, "props.txt").splitlines() if "=" in l)
    meta = dict(l.split("=", 1) for l in read(d, "collected.txt").splitlines() if "=" in l)
    battery = dict((k.strip(), v.strip()) for k, _, v in (l.partition(":") for l in read(d, "battery.txt").splitlines()) if _)
    mem = re.search(r"MemTotal:\s+(\d+)", read(d, "meminfo.txt"))
    cores = parse_cores(d)
    clusters = parse_clusters(d, cores)
    thermal = parse_thermal(read(d, "thermal.txt"))
    thermal_root = parse_thermal(read(d, "thermal.root.txt")) if read(d, "thermal.root.txt") else None
    codecs = parse_codecs(read(d, "codecs.xml.txt"))
    root = meta.get("root") == "1"
    power = parse_power(d)
    p = lambda k: props.get(k) or None  # noqa: E731
    soc = " ".join(x for x in (p("ro.soc.manufacturer"), p("ro.soc.model")) if x) or p("ro.chipname") or \
        p("ro.board.platform") or p("ro.hardware")
    abis64 = (p("ro.product.cpu.abilist64") or "").split(",") if p("ro.product.cpu.abilist64") else []
    s = {
        "model": p("ro.product.model"), "manufacturer": p("ro.product.manufacturer"), "codename": p("ro.product.device"),
        "serial": meta.get("serial"), "collected": meta.get("collected"),
        "android": p("ro.build.version.release"), "sdk": int(p("ro.build.version.sdk") or 0) or None,
        "fingerprint": p("ro.build.fingerprint"), "soc": soc, "platform": p("ro.board.platform"),
        "kernel": (read(d, "uname.txt").split() or [None, None, None])[2],
        "abilist": p("ro.product.cpu.abilist"), "arm64": "arm64-v8a" in abis64 or "arm64-v8a" in (p("ro.product.cpu.abilist") or ""),
        "ram_gb": round(int(mem[1]) / 1024 / 1024, 1) if mem else None,
        "battery": {"level": battery.get("level"), "status": battery.get("status"),
                    "temp_c": int(battery["temperature"]) / 10 if battery.get("temperature", "").isdigit() else None},
        "cores": len(cores), "clusters": clusters,
        "governor_readable": any(c["governor"] != "unreadable" for c in clusters),
        "cur_freq_readable": all(c["cur_freq_readable"] for c in clusters) if clusters else False,
        "thermal": thermal, "thermal_root": thermal_root, "power": power,
        "root": root, "selinux": meta.get("selinux"),
        "av1_decoders": sorted(n for n, c in codecs.items() if c["type"] == "video/av01" and not c["encoder"]),
        "av1_hw_decoder": any(c["type"] == "video/av01" and not c["encoder"] and not c["software"] for c in codecs.values()),
        "av2_codecs": sorted(n for n, c in codecs.items() if c["type"] != "video/av01"),
        "gpu": parse_gpu(d), "dsp": parse_dsp(d),
    }
    s["bench_flags"] = bench_flags(s)
    return s


def bench_flags(s):
    """Suggested bench.py options for this phone, as (options, why) pairs."""
    out = []
    if not s["arm64"]:
        out.append(("(none)", "no arm64-v8a ABI: the arm64 dav2d build will not run; an armv7 build is needed"))
    for c in s["clusters"]:
        out.append((f"--cpus {c['cpus']}", f"{c['count']}x {c['core']} only (policy{c['policy']})"))
    if s["thermal"]["cpu_zones_readable"]:
        out.append(("--cooldown-c <T>", f"cpu-* thermal zones readable ({s['thermal']['cpu_max_c']} °C when collected); "
                                        "set T a few degrees above the idle temperature with the clocks used"))
    else:
        out.append(("--pause 30", "no readable cpu-* thermal zone, so the --cooldown-c wait cannot work"))
    if s["root"]:
        out.append(("--lock-clocks", "root: the governor can be set"))
        if any(c["freqs_khz"] for c in s["clusters"]):
            out.append(("--freq POLICY:KHZ", "root: pins a policy at one of its frequency steps (listed below); "
                                             "scripts/freq_sweep.sh runs every step"))
        if s["power"]["input_suspend"] and s["power"]["current_now"]:
            out.append(("--battery-power", "root and battery/input_suspend: power readings on battery"))
        elif s["power"]["charge_controls"]:
            out.append(("(none)", f"charging is paused through {s['power']['charge_controls'][0]}, which bench.py does not use"))
    else:
        out.append(("(none)", "no root: no --lock-clocks, --freq or --battery-power; power readings include charging"))
    feats = set.intersection(*(set(c["cpumask_features"]) for c in s["clusters"])) if s["clusters"] else set()
    masks = ["0"] + [f for f in ("neon", "dotprod", "i8mm", "sve", "sve2") if f in feats]
    out.append((" / ".join(f"--cpumask {m}" for m in masks), "code paths every core supports (0 = plain C)"))
    return out


def mhz(khz):
    return f"{khz / 1000:.0f}" if khz else "?"


def markdown(s):
    yes = lambda b: "yes" if b else "no"  # noqa: E731
    t, pw, g, dsp = s["thermal"], s["power"], s["gpu"], s["dsp"]
    rows = [
        ("Model", f"{s['manufacturer']} {s['model']} (`{s['codename']}`, serial `{s['serial']}`)"),
        ("Android", f"{s['android']} (SDK {s['sdk']}), kernel {s['kernel']}"),
        ("SoC", f"{s['soc']} (platform `{s['platform']}`)"),
        ("ABIs", f"{s['abilist']}" + ("" if s["arm64"] else " — **no arm64: 32-bit only**")),
        ("RAM", f"{s['ram_gb']} GB"),
        ("Cores", f"{s['cores']}"),
    ]
    for c in s["clusters"]:
        gov = c["governor"] if c["governor"] != "unreadable" else f"unreadable ({c['governor_root']} with root)" \
            if c["governor_root"] else "unreadable"
        rows.append((f"policy{c['policy']}", f"cores {c['cpus']}: {c['count']}x {c['core']}, {mhz(c['min_khz'])}–"
                     f"{mhz(c['max_khz'])} MHz, {len(c['freqs_khz'])} steps, governor {gov}; "
                     f"{', '.join(c['cpumask_features']) or 'no feature flags'}"))
    rows += [
        ("Frequencies readable", f"current: {yes(s['cur_freq_readable'])}; min/max limits: "
                                 f"{yes(all(c['limits_readable'] for c in s['clusters']))}"),
        ("Thermal zones", f"{t['readable']} of {t['zones']} readable, {t['cpu_zones_readable']} `cpu-*` "
                          f"(bench.py cool-down {'works' if t['cpu_zones_readable'] else '**does not work**'})"
                          + (f"; with root {s['thermal_root']['cpu_zones_readable']} `cpu-*`" if s["thermal_root"] else "")),
        ("Battery sysfs", f"current_now {yes(pw['current_now'])}, voltage_now {yes(pw['voltage_now'])}, "
                          f"input_suspend {yes(pw['input_suspend'])}; current {pw['current_sign']}"
                          + (f", unit {pw['current_unit']}" if pw["current_unit"] else "")),
        ("Root", f"{yes(s['root'])} (SELinux {s['selinux']})"),
        ("AV1 decoders", f"{', '.join(s['av1_decoders']) or 'none listed'}; hardware: **{yes(s['av1_hw_decoder'])}**"),
        ("AV2 codecs", ", ".join(s["av2_codecs"]) or "none"),
        ("GPU", f"{g['gles'] or '?'}; Vulkan {g['vulkan'] or '?'}" + (f" ({g['vulkan_device']})" if g["vulkan_device"] else "")),
        ("DSP (FastRPC)", f"nodes: {', '.join(dsp['fastrpc_nodes']) or 'none'}; libcdsprpc: {yes(dsp['cdsp_lib'])}; "
                          f"unsigned PD shell: {'needs root to check' if dsp['unsigned_pd_shell'] is None else yes(dsp['unsigned_pd_shell'])}"),
        ("Collected", s["collected"]),
    ]
    lines = [f"# {s['manufacturer']} {s['model']}", "", "| | |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in rows]
    lines += ["", "## Suggested bench.py options", "", "| Option | Why |", "|---|---|"]
    lines += [f"| `{o}` | {w} |" if not o.startswith("(") else f"| — | {w} |" for o, w in s["bench_flags"]]
    lines += ["", "## Frequency steps (kHz)", ""]
    lines += [f"- policy{c['policy']} ({c['core']}): {' '.join(map(str, c['freqs_khz'])) or 'not readable'}"
              for c in s["clusters"]]
    return "\n".join(lines) + "\n"


def main(path):
    d = Path(path)
    s = summarize(d)
    (d / "summary.json").write_text(json.dumps(s, indent=2, ensure_ascii=False) + "\n")
    (d / "summary.md").write_text(markdown(s))
    print(markdown(s))


if __name__ == "__main__":
    main(sys.argv[1])
