"""X2-SV (left out of the main tables): its trial and combine floor ratios
against the minimum-hypothesis-floor proxy.

Usage: python3 -I sv_check.py <live-dir>
"""

import glob
import json
import os
import sys

LIVE = sys.argv[1]
ratios, comb = [], []
for f in sorted(glob.glob(os.path.join(LIVE, "ideas-x2-X2-SV-*.jsonl"))):
    rows = [json.loads(line) for line in open(f)]
    hyp = [r for r in rows if r["experiment"] == "ideas-x2-hypothesis" and r["floor_pct"] is not None]
    base = min(h["floor_pct"] for h in hyp)
    ratios += [h["floor_pct"] / base for h in hyp]
    run = next(r for r in rows if r["experiment"] == "ideas-x2-run")
    comb.append((os.path.basename(f), round(base, 3), round(run["floor_pct"] / base, 3)))
ratios.sort()
n = len(ratios)
print(f"X2-SV trials {n}: median {ratios[n//2]:.3f}, p90 {ratios[int(n*.9)]:.3f}, max {ratios[-1]:.3f}, "
      f">1.5x {sum(r > 1.5 for r in ratios)}, >2x {sum(r > 2 for r in ratios)}")
print("combine (file, proxy base, ratio):", comb)
