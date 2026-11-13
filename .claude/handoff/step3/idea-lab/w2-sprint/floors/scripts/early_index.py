"""Run-start effect or VM-uptime effect? Share of trials above 1.5x by trial
index within the run, for first cases (fresh VM) and later cases (VM already
up 10-45 min).

Usage: python3 -I early_index.py <out-dir>   (reads trials.csv)
"""
import csv, os, sys
OUT = sys.argv[1]
T = [t for t in csv.DictReader(open(os.path.join(OUT, "trials.csv"))) if t["floor"] not in ("", "None")]
for t in T:
    t["ratio"] = float(t["floor"]) / float(t["calib_recorded"] or t["calib_proxy_min"])
for pos in ("first case", "later case"):
    for lo, hi in ((1, 4), (5, 8), (9, 12), (13, 99)):
        xs = [t["ratio"] for t in T if (t["case_position"] == "1") == (pos == "first case") and lo <= int(t["index"]) <= hi]
        if xs:
            print(f"{pos}, trials {lo}-{hi if hi < 99 else '+'}: n {len(xs)}, >1.5x {sum(x > 1.5 for x in xs)/len(xs):.3f}, >2x {sum(x > 2 for x in xs)/len(xs):.3f}, mean {sum(xs)/len(xs):.3f}")
