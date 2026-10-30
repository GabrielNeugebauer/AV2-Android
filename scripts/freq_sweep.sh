#!/usr/bin/env bash
# Frequency sweep: runs bench.py once per available frequency of one CPU cluster, with the decoder kept on that
# cluster's cores, on battery. Shows how decoding speed and energy scale with clock speed on one core type.
#
# Usage (from the AV2-Android folder):
#   scripts/freq_sweep.sh <serial> <policy> <cpus> <threads> <out.csv> <stream.obu>...
# Examples on the Redmi (policy0 = six A55 cores 0-5, policy6 = two A76 cores 6-7):
#   scripts/freq_sweep.sh e113b3850013 0 0-5 1 results/sweep_a55.csv streams/poc/*.obu
#   scripts/freq_sweep.sh e113b3850013 6 6-7 1 results/sweep_a76.csv streams/poc/*.obu
# Environment: RUNS (default 5), COOLDOWN_C (default 58), FREQS (to sweep only some steps, e.g. "576000 1017600").
set -euo pipefail
SERIAL=$1 POLICY=$2 CPUS=$3 THREADS=$4 OUT=$5
shift 5

FREQS=${FREQS:-$(adb -s "$SERIAL" shell -n "cat /sys/devices/system/cpu/cpufreq/policy$POLICY/scaling_available_frequencies")}
for f in $FREQS; do
    echo "== policy$POLICY at $f kHz, cores $CPUS, $THREADS thread(s)"
    .venv/bin/python scripts/bench.py --serial "$SERIAL" --streams "$@" --runs "${RUNS:-5}" --threads "$THREADS" \
        --cpus "$CPUS" --freq "$POLICY:$f" --battery-power \
        --cooldown-c "${COOLDOWN_C:-58}" --cooldown-timeout 30 --out "$OUT"
done
