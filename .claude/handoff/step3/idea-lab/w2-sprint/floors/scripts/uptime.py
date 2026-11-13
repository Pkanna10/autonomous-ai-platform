"""Floor ratio against the job's elapsed time at the trial (a VM-uptime proxy):
elapsed = earlier cases' seconds_measured + (index - 0.5) / trials x this run's
seconds_measured (trials assumed evenly spaced; no per-trial timestamp exists).

Usage: python3 -I uptime.py <out-dir>   (reads trials.csv, runs.csv); writes uptime.csv
"""
import csv, os, sys
OUT = sys.argv[1]
T = [t for t in csv.DictReader(open(os.path.join(OUT, "trials.csv"))) if t["floor"] not in ("", "None")]
R = {(r["dispatch"], r["library"]): r for r in csv.DictReader(open(os.path.join(OUT, "runs.csv")))}
rows, bins = [], [(0, 5), (5, 10), (10, 15), (15, 20), (20, 30), (30, 60)]
for t in T:
    r = R[(t["dispatch"], t["library"])]
    el = float(t["elapsed_before_s"]) + (int(t["index"]) - 0.5) / int(r["trials"]) * float(r["seconds_measured"])
    t["elapsed_min"] = el / 60
    t["ratio"] = float(t["floor"]) / float(t["calib_recorded"] or t["calib_proxy_min"])
for kind in ("all", "one-run", "multi-run"):
    for lo, hi in bins:
        xs = [t for t in T if lo <= t["elapsed_min"] < hi and (kind == "all" or (t["cases_in_dispatch"] == "1") == (kind == "one-run"))]
        if xs:
            rows.append({"dispatches": kind, "elapsed_min": f"{lo}-{hi}", "trials": len(xs), "runs": len({(t['dispatch'], t['library']) for t in xs}),
                         "share_gt_1.5": round(sum(t["ratio"] > 1.5 for t in xs) / len(xs), 3),
                         "share_gt_2": round(sum(t["ratio"] > 2 for t in xs) / len(xs), 3),
                         "mean_ratio": round(sum(t["ratio"] for t in xs) / len(xs), 3)})
with open(os.path.join(OUT, "uptime.csv"), "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
for r in rows: print(r)
