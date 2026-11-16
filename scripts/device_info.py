"""Collects a phone's specifications over adb: Android build, SoC, CPU cores and clusters, frequencies and governors,
thermal zones, battery sysfs files, AV1/AV2 codecs, GPU, Vulkan and DSP. Works without root; when `su -c id` works
it also records what only root can read (*.root.txt). Raw outputs go to devices/<codename>/raw/, then
device_summary.py writes summary.md and summary.json next to them.

Interactive: python3 scripts/device_info.py   (asks for the phone and the output folder)
"""
import datetime
import re
import shlex
import subprocess
import sys
from pathlib import Path

import device_summary
from interativo import ROOT, ask_text, choose_phone, confirm_or_exit, has_root

PROPS = """ro.product.model ro.product.manufacturer ro.product.brand ro.product.device ro.product.name ro.product.board
ro.build.version.release ro.build.version.sdk ro.build.display.id ro.build.fingerprint ro.product.cpu.abi
ro.product.cpu.abilist ro.product.cpu.abilist32 ro.product.cpu.abilist64 ro.soc.manufacturer ro.soc.model
ro.board.platform ro.hardware ro.chipname ro.hardware.chipname ro.hardware.egl ro.hardware.vulkan
ro.opengles.version""".split()

CPUS = """for c in /sys/devices/system/cpu/cpu[0-9]*; do
  echo "${c##*/} $(cat $c/regs/identification/midr_el1 2>/dev/null || echo unreadable) $(cat $c/online 2>/dev/null || echo 1)"
done"""
CPUFREQ = """for p in /sys/devices/system/cpu/cpufreq/policy*; do
  for f in related_cpus cpuinfo_min_freq cpuinfo_max_freq scaling_min_freq scaling_max_freq scaling_cur_freq \\
           scaling_available_frequencies scaling_boost_frequencies scaling_available_governors scaling_governor; do
    [ -e $p/$f ] || continue
    v=$(cat $p/$f 2>/dev/null) || v=unreadable
    echo "${p##*/} $f ${v:-unreadable}"
  done
done"""
THERMAL = """for z in /sys/class/thermal/thermal_zone*; do
  t=$(cat $z/type 2>/dev/null) || t=unreadable
  v=$(cat $z/temp 2>/dev/null) || v=unreadable
  echo "${z##*/} ${t:-unreadable} ${v:-unreadable}"
done"""
# Battery files bench.py uses (and other names some kernels use to pause charging), then 5 current samples:
# with the cable in, their sign while charging gives the sign convention of current_now.
POWER = """b=/sys/class/power_supply/battery
echo "supplies $(ls /sys/class/power_supply 2>/dev/null | tr "\\n" " ")"
for n in current_now voltage_now status capacity temp input_suspend charging_enabled battery_charging_enabled charge_disable; do
  f=$b/$n
  if [ -e $f ]; then
    r=1; v=$(cat $f 2>/dev/null) || { r=0; v=unreadable; }
    w=0; [ -w $f ] && w=1
    echo "file $n exists=1 r=$r w=$w mode=$(ls -l $f | cut -d" " -f1) value=$v"
  else
    echo "file $n exists=0"
  fi
done
for i in 1 2 3 4 5; do echo "sample $(cat $b/status 2>/dev/null) $(cat $b/current_now 2>/dev/null) $(cat $b/voltage_now 2>/dev/null)"; sleep 0.5; done"""
# Every media codec list that mentions AV1 (video/av01) or a later AOM codec (video/av0*)
CODECS = """for f in /vendor/etc/media_codecs*.xml /odm/etc/media_codecs*.xml /system/etc/media_codecs*.xml \\
         /product/etc/media_codecs*.xml /apex/com.android.media.swcodec/etc/media_codecs*.xml; do
  [ -r $f ] && grep -q -i "video/av0" $f && { echo "### $f"; cat $f; }
done"""
GPU = """echo "gles $(dumpsys SurfaceFlinger | grep -m1 GLES)"
for d in /vendor/lib64/hw /vendor/lib/hw; do ls $d 2>/dev/null | grep -i vulkan | sed "s|^|vulkan_lib $d/|"; done"""
DSP = """echo "## nodes"; ls -l /dev/adsprpc* /dev/fastrpc* 2>&1
echo "## public libs"; grep -i -E "rpc|dsp" /vendor/etc/public.libraries.txt 2>&1
echo "## /vendor/dsp"; ls -R /vendor/dsp 2>&1 | head -200"""
DSP_ROOT = DSP + """
echo "## fastrpc shells"; find /vendor/dsp /vendor/lib/rfsa /vendor/lib64 /dsp -iname "fastrpc_shell*" 2>/dev/null"""


def collect(serial, out_dir):
    """Writes the raw files and the summary for one phone. Returns the phone's folder."""
    def run(cmd, root=False):
        # Remote failures (missing files, permission denied) are part of the data, so they never stop the script.
        if root:
            cmd = f"su -c {shlex.quote(cmd)}"
        res = subprocess.run(["adb", "-s", serial, "shell", cmd], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, errors="replace")
        return res.stdout.replace("\r", "")

    name = run("getprop ro.product.device").strip() or run("getprop ro.product.model").strip()
    d = Path(out_dir) / re.sub(r"[^A-Za-z0-9._-]", "_", name)
    raw = d / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    root = has_root(serial)
    print(f"Coletando em {d} (root: {'sim' if root else 'não'})...")
    (raw / "collected.txt").write_text(
        f"serial={serial}\ncollected={datetime.datetime.now().astimezone().isoformat(timespec='seconds')}\n"
        f"root={int(root)}\nselinux={run('getenforce').strip()}\n")
    files = {
        "props.txt": f'for p in {" ".join(PROPS)}; do echo "$p=$(getprop $p)"; done',
        "uname.txt": "uname -a", "meminfo.txt": "cat /proc/meminfo", "battery.txt": "dumpsys battery",
        "cpuinfo.txt": "cat /proc/cpuinfo", "cpus.txt": CPUS, "cpufreq.txt": CPUFREQ, "thermal.txt": THERMAL,
        "power.txt": POWER, "codecs.xml.txt": CODECS, "gpu.txt": GPU, "features.txt": "pm list features",
        "vkjson.json": "cmd gpu vkjson", "dsp.txt": DSP,
    }
    for filename, cmd in files.items():
        (raw / filename).write_text(run(cmd))
    if root:
        for filename, cmd in {"cpufreq.root.txt": CPUFREQ, "thermal.root.txt": THERMAL, "dsp.root.txt": DSP_ROOT}.items():
            (raw / filename).write_text(run(cmd, root=True))
    device_summary.main(d)
    return d


def main():
    serial = choose_phone()
    out_dir = ROOT / ask_text("\nPasta de saída (dentro do AV2-Android)", "devices")
    confirm_or_exit("Coletar? [s/N]: ")
    collect(serial, out_dir)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nCancelado.")
