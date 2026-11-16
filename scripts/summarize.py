"""Summarizes a bench.py CSV: median, min and max fps and median power per decoder, stream, threads and code path.

Interactive: python3 scripts/summarize.py   (picks a CSV from results/)

CSVs from before bench.py had the decoder column have no decoder column; their rows are dav2d.
"""

import csv
import statistics
import sys

from interativo import ROOT, menu


def summarize(path):
    with open(path) as f:
        rows = list(csv.DictReader(f))
    groups = {}
    for r in rows:
        key = (r.get("decoder", "dav2d"), r["stream"], int(r["threads"]),
               "NEON" if r["cpumask"] == "all" else f"cpumask {r['cpumask']}")
        groups.setdefault(key, []).append(r)

    print(f"{'decoder':7} {'stream':45} {'thr':>3} {'code':10} {'median fps':>10} {'min-max fps':>15} {'median mW':>9}")
    for (decoder, stream, threads, code), g in sorted(groups.items()):
        fps = [float(r["fps"]) for r in g]
        mw = [float(r["power_mw"]) for r in g]
        print(f"{decoder:7} {stream:45} {threads:>3} {code:10} {statistics.median(fps):10.1f} "
              f"{min(fps):7.1f}-{max(fps):<7.1f} {statistics.median(mw):9.0f}")
    print(f"\n{len(rows)} runs, all MD5 correct: {all(r['md5_ok'] == 'True' for r in rows)}")


def main():
    csvs = sorted((ROOT / "results").rglob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not csvs:
        sys.exit("Nenhum CSV em results/.")
    path = csvs[menu("RESULTADOS (mais recentes primeiro)", [str(p.relative_to(ROOT)) for p in csvs],
                     "Selecione o CSV (em branco = 1): ", default=0)]
    print()
    summarize(path)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nCancelado.")
