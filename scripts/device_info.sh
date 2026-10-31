#!/usr/bin/env bash
# Collects a phone's specifications over adb: Android build, SoC, CPU cores and clusters, frequencies and governors,
# thermal zones, battery sysfs files, AV1/AV2 codecs, GPU, Vulkan and DSP. Works without root; when `su -c id` works
# it also records what only root can read (*.root.txt). Raw outputs go to <out_dir>/<codename>/raw/, then
# scripts/device_summary.py writes summary.md and summary.json next to them.
# Usage: scripts/device_info.sh <adb serial> [out_dir]   (run from the AV2-Android folder; out_dir defaults to devices)
set -euo pipefail
SERIAL=${1:?usage: $0 <adb serial> [out_dir]}
OUT=${2:-devices}
ADB=(adb -s "$SERIAL")

# Remote failures (missing files, permission denied) are part of the data, so they never stop the script.
run() { "${ADB[@]}" shell -n "$1" 2>&1 | tr -d '\r' || true; }
quote() { printf "'%s'" "${1//\'/\'\\\'\'}"; }
run_root() { "${ADB[@]}" shell -n "su -c $(quote "$1")" 2>&1 | tr -d '\r' || true; }

"${ADB[@]}" get-state >/dev/null
name=$(run 'getprop ro.product.device')
[ -n "$name" ] || name=$(run 'getprop ro.product.model')
name=${name//[^A-Za-z0-9._-]/_}
DIR=$OUT/$name
R=$DIR/raw
mkdir -p "$R"

if timeout 20 "${ADB[@]}" shell -n 'su -c id' 2>/dev/null | grep -q 'uid=0'; then ROOT=1; else ROOT=0; fi
printf 'serial=%s\ncollected=%s\nroot=%s\nselinux=%s\n' "$SERIAL" "$(date -Iseconds)" "$ROOT" \
    "$(run getenforce)" > "$R/collected.txt"

PROPS="ro.product.model ro.product.manufacturer ro.product.brand ro.product.device ro.product.name ro.product.board
ro.build.version.release ro.build.version.sdk ro.build.display.id ro.build.fingerprint ro.product.cpu.abi
ro.product.cpu.abilist ro.product.cpu.abilist32 ro.product.cpu.abilist64 ro.soc.manufacturer ro.soc.model
ro.board.platform ro.hardware ro.chipname ro.hardware.chipname ro.hardware.egl ro.hardware.vulkan ro.opengles.version"
run "for p in ${PROPS//$'\n'/ }; do echo \"\$p=\$(getprop \$p)\"; done" > "$R/props.txt"
run 'uname -a' > "$R/uname.txt"
run 'cat /proc/meminfo' > "$R/meminfo.txt"
run 'dumpsys battery' > "$R/battery.txt"
run 'cat /proc/cpuinfo' > "$R/cpuinfo.txt"
run 'for c in /sys/devices/system/cpu/cpu[0-9]*; do
  echo "${c##*/} $(cat $c/regs/identification/midr_el1 2>/dev/null || echo unreadable) $(cat $c/online 2>/dev/null || echo 1)"
done' > "$R/cpus.txt"

CPUFREQ='for p in /sys/devices/system/cpu/cpufreq/policy*; do
  for f in related_cpus cpuinfo_min_freq cpuinfo_max_freq scaling_min_freq scaling_max_freq scaling_cur_freq \
           scaling_available_frequencies scaling_boost_frequencies scaling_available_governors scaling_governor; do
    [ -e $p/$f ] || continue
    v=$(cat $p/$f 2>/dev/null) || v=unreadable
    echo "${p##*/} $f ${v:-unreadable}"
  done
done'
THERMAL='for z in /sys/class/thermal/thermal_zone*; do
  t=$(cat $z/type 2>/dev/null) || t=unreadable
  v=$(cat $z/temp 2>/dev/null) || v=unreadable
  echo "${z##*/} ${t:-unreadable} ${v:-unreadable}"
done'
run "$CPUFREQ" > "$R/cpufreq.txt"
run "$THERMAL" > "$R/thermal.txt"

# Battery files bench.py uses (and other names some kernels use to pause charging), then 5 current samples:
# with the cable in, their sign while charging gives the sign convention of current_now.
run 'b=/sys/class/power_supply/battery
echo "supplies $(ls /sys/class/power_supply 2>/dev/null | tr "\n" " ")"
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
for i in 1 2 3 4 5; do echo "sample $(cat $b/status 2>/dev/null) $(cat $b/current_now 2>/dev/null) $(cat $b/voltage_now 2>/dev/null)"; sleep 0.5; done' \
    > "$R/power.txt"

# Every media codec list that mentions AV1 (video/av01) or a later AOM codec (video/av0*)
run 'for f in /vendor/etc/media_codecs*.xml /odm/etc/media_codecs*.xml /system/etc/media_codecs*.xml \
         /product/etc/media_codecs*.xml /apex/com.android.media.swcodec/etc/media_codecs*.xml; do
  [ -r $f ] && grep -q -i "video/av0" $f && { echo "### $f"; cat $f; }
done' > "$R/codecs.xml.txt"

run 'echo "gles $(dumpsys SurfaceFlinger | grep -m1 GLES)"
for d in /vendor/lib64/hw /vendor/lib/hw; do ls $d 2>/dev/null | grep -i vulkan | sed "s|^|vulkan_lib $d/|"; done' > "$R/gpu.txt"
run 'pm list features' > "$R/features.txt"
run 'cmd gpu vkjson' > "$R/vkjson.json"

DSP='echo "## nodes"; ls -l /dev/adsprpc* /dev/fastrpc* 2>&1
echo "## public libs"; grep -i -E "rpc|dsp" /vendor/etc/public.libraries.txt 2>&1
echo "## /vendor/dsp"; ls -R /vendor/dsp 2>&1 | head -200'
run "$DSP" > "$R/dsp.txt"

if [ "$ROOT" = 1 ]; then
    run_root "$CPUFREQ" > "$R/cpufreq.root.txt"
    run_root "$THERMAL" > "$R/thermal.root.txt"
    run_root "$DSP"'
echo "## fastrpc shells"; find /vendor/dsp /vendor/lib/rfsa /vendor/lib64 /dsp -iname "fastrpc_shell*" 2>/dev/null' > "$R/dsp.root.txt"
fi

python3 "$(dirname "$0")/device_summary.py" "$DIR"
