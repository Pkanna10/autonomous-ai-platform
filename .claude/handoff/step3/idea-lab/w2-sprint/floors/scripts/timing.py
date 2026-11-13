"""Are a dispatch's cases sequential? 'Run live tests' step wall time against
the sum of its runs' seconds_measured; and how quiet the replay VM was
against live runs over a comparable number of looks.

Usage: python3 -I timing.py <out-dir>   (reads gh/job_steps.json, runs.csv, trials.csv)
Writes sequential_check.csv.
"""
import csv, json, os, sys
from datetime import datetime
OUT = sys.argv[1]
J = json.load(open(os.path.join(OUT, "gh", "job_steps.json")))["jobs"]
R = list(csv.DictReader(open(os.path.join(OUT, "runs.csv"))))
ts = lambda s: datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").timestamp()
rows = []
for j in J:
    mine = [r for r in R if r["dispatch"] == j["dispatch"]]
    if not mine:
        continue
    step = ts(j["completed"]) - ts(j["started"])
    total = sum(float(r["seconds_measured"]) for r in mine)
    rows.append({"dispatch": j["dispatch"], "cases": len(mine), "step_s": step, "sum_seconds_measured": round(total, 1),
                 "step_minus_sum_s": round(step - total, 1), "max_single_case_s": max(float(r["seconds_measured"]) for r in mine)})
with open(os.path.join(OUT, "sequential_check.csv"), "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
for r in rows: print(r)
# replay quietness: 12 looks, max ratio 1.03. Live: runs whose first 12 trials all <= 1.03
T = [t for t in csv.DictReader(open(os.path.join(OUT, "trials.csv"))) if t["floor"] not in ("", "None")]
runs = {}
for t in T:
    b = float(t["calib_recorded"] or t["calib_proxy_min"])
    runs.setdefault((t["dispatch"], t["library"]), []).append((int(t["index"]), float(t["floor"]) / b))
quiet12 = sum(1 for v in runs.values() if all(x <= 1.03 for _, x in sorted(v)[:12]))
none15 = sum(1 for v in runs.values() if all(x <= 1.5 for _, x in v))
print(f"live runs whose first 12 trials all <= 1.03x: {quiet12} of {len(runs)}; runs with no trial > 1.5x: {none15} of {len(runs)}")
