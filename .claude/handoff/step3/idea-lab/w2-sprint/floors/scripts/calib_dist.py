"""Run calibrations (recorded, else the minimum-hypothesis-floor proxy) per
library, against the quiet replay's.

Usage: python3 -I calib_dist.py <out-dir>   (reads runs.csv); writes calib_dist.csv
"""
import csv, os, statistics as st, sys
OUT = sys.argv[1]
R = list(csv.DictReader(open(os.path.join(OUT, "runs.csv"))))
rows = []
for lib in ("sqlparse", "tomli", "mistune", "markdown"):
    xs = sorted(float(r["calib_recorded"] or r["calib_proxy_min"]) for r in R if r["library"] == lib)
    rows.append({"library": lib, "runs": len(xs), "at_2.00_clamp": sum(1 for x in xs if x < 2.0005),
                 "median": round(st.median(xs), 2), "max": round(xs[-1], 2),
                 "above_quiet": sum(1 for x in xs if x > float(next(r["calib_quiet"] for r in R if r["library"] == lib)) + 1e-6),
                 "quiet_replay": next(r["calib_quiet"] for r in R if r["library"] == lib), "values": " ".join(f"{x:.2f}" for x in xs)})
with open(os.path.join(OUT, "calib_dist.csv"), "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
for r in rows: print(r)
