"""Run-level effects: clustering, library x position, within-run trend, and
concurrent dispatches.

Usage: python3 -I covariates.py <out-dir> <workflow_runs.json>
Reads trials.csv, runs.csv (load.py), dispatch_times.csv; writes
lib_position.csv, within_run.csv, concurrency.csv, sequential_check.csv.
"""

import csv
import json
import math
import os
import random
import statistics as st
import sys
from datetime import datetime

OUT, WR = sys.argv[1], sys.argv[2]
T = [t for t in csv.DictReader(open(os.path.join(OUT, "trials.csv"))) if t["floor"] not in ("", "None")]
R = list(csv.DictReader(open(os.path.join(OUT, "runs.csv"))))
for t in T:
    t["floor"] = float(t["floor"])
    base = t["calib_recorded"] if t["calib_recorded"] not in ("", "None") else t["calib_proxy_min"]
    t["base"] = float(base)
    t["ratio"] = t["floor"] / t["base"]
    t["index"] = int(t["index"])
    t["case_position"] = int(t["case_position"])


def write(name, rows):
    fields = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with open(os.path.join(OUT, name), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def share(xs, cut=1.5):
    return round(sum(1 for x in xs if x > cut) / len(xs), 3) if xs else None


# 1 over-dispersion: is a trial's >1.5x a run property?
runs = {}
for t in T:
    runs.setdefault((t["dispatch"], t["library"]), []).append(t)
p = sum(t["ratio"] > 1.5 for t in T) / len(T)
counts = [sum(t["ratio"] > 1.5 for t in v) for v in runs.values()]
sizes = [len(v) for v in runs.values()]
obs_var = st.pvariance(counts)
exp_var = st.mean([n * p * (1 - p) for n in sizes])
# permutation: shuffle the >1.5 flags across trials, keep run sizes
flags = [t["ratio"] > 1.5 for t in T]
rng = random.Random(7)
top10_obs = sum(sorted(counts, reverse=True)[:10])
perm_top10 = []
for _ in range(2000):
    rng.shuffle(flags)
    i, cs = 0, []
    for n in sizes:
        cs.append(sum(flags[i:i + n]))
        i += n
    perm_top10.append(sum(sorted(cs, reverse=True)[:10]))
print(f"trials {len(T)}, runs {len(runs)}, share >1.5x {p:.3f}")
print(f"per-run count variance observed {obs_var:.2f} vs binomial {exp_var:.2f} (dispersion {obs_var/exp_var:.2f})")
print(f"top-10 runs hold {top10_obs} of {sum(counts)} >1.5x trials; permutation mean {st.mean(perm_top10):.1f}, "
      f"max {max(perm_top10)}, p(>=obs) {sum(x >= top10_obs for x in perm_top10)/len(perm_top10):.4f}")

# 2 library x position
rows = []
for lib in ("sqlparse", "tomli", "mistune", "markdown"):
    for pos in ("first", "later"):
        xs = [t for t in T if t["library"] == lib and ((t["case_position"] == 1) == (pos == "first"))]
        if not xs:
            continue
        rows.append({"library": lib, "position": pos, "runs": len({t["dispatch"] for t in xs}), "trials": len(xs),
                     "share_gt_1.5": share([t["ratio"] for t in xs]), "share_gt_2": share([t["ratio"] for t in xs], 2.0),
                     "median_floor_pct": round(st.median([t["floor"] for t in xs]), 2),
                     "p90_floor_pct": round(sorted(t["floor"] for t in xs)[int(len(xs) * .9)], 2),
                     "median_base_pct": round(st.median([t["base"] for t in xs]), 2)})
write("lib_position.csv", rows)
print("\nlibrary x position")
for r in rows:
    print(r)
# X2-D and X2-P only (fixed order: sqlparse/mistune first, tomli/markdown second)
for arm in ("X2-D", "X2-P", "X2-0"):
    for pos in (1, 2, 3):
        xs = [t["ratio"] for t in T if t["arm"] == arm and t["case_position"] == pos and t["cases_in_dispatch"] != "1"]
        if xs:
            print(f" {arm} multi-run position {pos}: n {len(xs)} share>1.5 {share(xs)}")

# 3 within-run trend: first third vs last third of each run's trials
diffs, rows = [], []
for key, v in runs.items():
    v = sorted(v, key=lambda t: t["index"])
    k = max(1, len(v) // 3)
    a, b = [t["ratio"] for t in v[:k]], [t["ratio"] for t in v[-k:]]
    fa, fb = [t["floor"] for t in v[:k]], [t["floor"] for t in v[-k:]]
    rows.append({"dispatch": key[0], "library": key[1], "trials": len(v),
                 "first_third_mean_floor": round(st.mean(fa), 3), "last_third_mean_floor": round(st.mean(fb), 3),
                 "first_third_gt1.5": sum(x > 1.5 for x in a), "last_third_gt1.5": sum(x > 1.5 for x in b)})
    diffs.append(st.mean(fb) - st.mean(fa))
write("within_run.csv", rows)
up = sum(1 for d in diffs if d > 1e-9)
down = sum(1 for d in diffs if d < -1e-9)
print(f"\nwithin run, last third minus first third mean floor: higher in {up}, lower in {down}, equal in {len(diffs)-up-down}; "
      f"median {st.median(diffs):+.3f} pts; first-third >1.5x {sum(r['first_third_gt1.5'] for r in rows)}, last-third {sum(r['last_third_gt1.5'] for r in rows)}")

# 4 concurrency: other workflow_dispatch runs of the repo overlapping each dispatch
wr = json.load(open(WR))["workflow_runs"]


def ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").timestamp()


spans = [(str(r["id"]), ts(r["run_started_at"]), ts(r["updated_at"])) for r in wr]
by_id = {i: (s, e) for i, s, e in spans}
crow = []
for (d, lib), v in runs.items():
    s, e = by_id[d]
    # time-weighted mean number of other runs alive during this dispatch
    pts = sorted({s, e, *[x for _, a, b in spans for x in (a, b) if s < x < e]})
    tot = 0.0
    for a, b in zip(pts, pts[1:]):
        mid = (a + b) / 2
        tot += (b - a) * sum(1 for i, x, y in spans if i != d and x <= mid <= y)
    conc = tot / (e - s)
    xs = [t["ratio"] for t in v]
    crow.append({"dispatch": d, "library": lib, "arm": v[0]["arm"], "concurrent_mean": round(conc, 2),
                 "started_utc": datetime.utcfromtimestamp(s).strftime("%m-%d %H:%M"),
                 "trials": len(v), "gt_1.5": sum(x > 1.5 for x in xs), "share_gt_1.5": share(xs),
                 "base": v[0]["base"]})
write("concurrency.csv", crow)
print("\nconcurrency (other dispatches of the repo alive, time-weighted)")
for lo, hi in ((0, 1.5), (1.5, 3.5), (3.5, 6), (6, 99)):
    sel = [t for c in crow if lo <= c["concurrent_mean"] < hi for t in runs[(c["dispatch"], c["library"])]]
    xs = [t["ratio"] for t in sel]
    nruns = sum(1 for c in crow if lo <= c["concurrent_mean"] < hi)
    if xs:
        print(f" [{lo},{hi}): runs {nruns}, trials {len(xs)}, share>1.5 {share(xs)}, share>2 {share(xs, 2.0)}")
# rank correlation run share vs concurrency
def rank(v):
    o = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(o):
        j = i
        while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
            j += 1
        for k in range(i, j + 1):
            r[o[k]] = (i + j) / 2
        i = j + 1
    return r
a, b = rank([c["concurrent_mean"] for c in crow]), rank([c["share_gt_1.5"] for c in crow])
ma, mb = st.mean(a), st.mean(b)
rho = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
print(f" Spearman(run concurrency, run share >1.5x) = {rho:.2f} over {len(crow)} runs")
