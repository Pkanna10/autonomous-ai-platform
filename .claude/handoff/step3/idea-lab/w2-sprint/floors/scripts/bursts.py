"""Within-run structure: floor by position normalised per run, and whether a
high floor follows a high floor (bursts) more than chance.

Usage: python3 -I bursts.py <out-dir>   (reads trials.csv); writes by_index.csv
"""

import csv
import os
import statistics as st
import sys

OUT = sys.argv[1]
T = [t for t in csv.DictReader(open(os.path.join(OUT, "trials.csv"))) if t["floor"] not in ("", "None")]
runs = {}
for t in T:
    t["floor"] = float(t["floor"])
    base = t["calib_recorded"] if t["calib_recorded"] not in ("", "None") else t["calib_proxy_min"]
    t["ratio"] = t["floor"] / float(base)
    t["index"] = int(t["index"])
    runs.setdefault((t["dispatch"], t["library"]), []).append(t)

# 1 floor relative to the run's own mean floor, by trial index
by = {}
for v in runs.values():
    m = st.mean(t["floor"] for t in v)
    for t in v:
        b = min(t["index"], 16)
        by.setdefault(b, []).append((t["floor"] / m, t["ratio"] > 1.5))
rows = []
for b in sorted(by):
    xs = by[b]
    rows.append({"index": f"{b}" if b < 16 else "16+", "trials": len(xs),
                 "mean_floor_over_run_mean": round(st.mean(x for x, _ in xs), 3),
                 "share_gt_1.5": round(sum(h for _, h in xs) / len(xs), 3)})
with open(os.path.join(OUT, "by_index.csv"), "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
for r in rows:
    print(r)

# 2 bursts: P(high | previous trial high) vs P(high | previous not high), within run
hh = hn = nh = nn = 0
for v in runs.values():
    v = sorted(v, key=lambda t: t["index"])
    for a, b in zip(v, v[1:]):
        pa, pb = a["ratio"] > 1.5, b["ratio"] > 1.5
        if pa and pb:
            hh += 1
        elif pa:
            hn += 1
        elif pb:
            nh += 1
        else:
            nn += 1
print(f"\nP(high | prev high) = {hh}/{hh+hn} = {hh/(hh+hn):.3f};  P(high | prev not high) = {nh}/{nh+nn} = {nh/(nh+nn):.3f}")

# 3 the same within runs only, controlling run level: shuffle order inside each run
import random
rng = random.Random(11)
sims = []
for _ in range(2000):
    a_hh = a_h = 0
    for v in runs.values():
        flags = [t["ratio"] > 1.5 for t in v]
        rng.shuffle(flags)
        for x, y in zip(flags, flags[1:]):
            if x:
                a_h += 1
                a_hh += y
    sims.append(a_hh / a_h if a_h else 0)
obs = hh / (hh + hn)
print(f"within-run shuffle: P(high|prev high) mean {st.mean(sims):.3f}, p(>=obs) {sum(s >= obs for s in sims)/len(sims):.4f}")
