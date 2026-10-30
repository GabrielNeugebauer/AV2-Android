"""Summarizes a bench.py CSV: median, min and max fps and median power per stream, threads and code path.

Usage (from the AV2-Android folder):
    python scripts/summarize.py results/poc.csv
"""

import csv
import statistics
import sys


def main(path):
    rows = list(csv.DictReader(open(path)))
    groups = {}
    for r in rows:
        key = (r["stream"], int(r["threads"]), "NEON" if r["cpumask"] == "all" else f"cpumask {r['cpumask']}")
        groups.setdefault(key, []).append(r)

    print(f"{'stream':45} {'thr':>3} {'code':10} {'median fps':>10} {'min-max fps':>15} {'median mW':>9}")
    for (stream, threads, code), g in sorted(groups.items()):
        fps = [float(r["fps"]) for r in g]
        mw = [float(r["power_mw"]) for r in g]
        print(f"{stream:45} {threads:>3} {code:10} {statistics.median(fps):10.1f} "
              f"{min(fps):7.1f}-{max(fps):<7.1f} {statistics.median(mw):9.0f}")
    print(f"\n{len(rows)} runs, all MD5 correct: {all(r['md5_ok'] == 'True' for r in rows)}")


if __name__ == "__main__":
    main(sys.argv[1])
