"""Monte Carlo of the two floor rules under stationary noise (no contention).

Calibration (trial_runner.py:816-859): 3 A/A blocks, each 5 timed runs per side
(warm-ups untimed), gap = |mean A - mean A'| / max(mean A, mean A'), floor =
max(2 %, 2 x largest gap).
Trial floor (anticheat.py:207-217, 231-232): max(2 sd_A, 2 sd_B, cal x mean_A) / mean_A,
sd the sample stdev of the 5 timed runs (RunStats, n-1).

Noise models per timed run (relative to a mean of 1):
  gauss(s):      N(0, s)
  outlier(s,p,d): N(0, s) plus, with probability p, a +d slowdown (one-sided spike)
  drift(s,r):    N(0, s) per run plus a per-measurement offset N(0, r) shared by
                 both sides of the same block (cancels in gaps and sds: control)
Usage: python3 -I simulate.py <out-dir>   writes sim.csv
"""

import csv
import os
import random
import statistics as st
import sys

OUT = sys.argv[1]
RUNS, BLOCKS, MIN_FLOOR, K = 5, 3, 0.02, 2.0
RUNS_PER_TRIAL = 15  # a run's trials share one calibration
SIMS = 4000


def sample(model, rng):
    kind = model[0]
    if kind == "gauss":
        return 1 + rng.gauss(0, model[1])
    if kind == "outlier":
        _, s, p, d = model
        return 1 + rng.gauss(0, s) + (d if rng.random() < p else 0.0)
    raise ValueError(kind)


def side(model, rng, n=RUNS):
    return [sample(model, rng) for _ in range(n)]


def calibrate(model, rng):
    gap = 0.0
    for _ in range(BLOCKS):
        a, b = side(model, rng), side(model, rng)
        ma, mb = st.mean(a), st.mean(b)
        gap = max(gap, abs(ma - mb) / max(ma, mb))
    return max(MIN_FLOOR, K * gap)


def trial_floor(model, rng, cal):
    a, b = side(model, rng), side(model, rng)
    ma = st.mean(a)
    return max(K * st.stdev(a), K * st.stdev(b), cal * ma) / ma


def run(model, rng):
    ratios = []
    for _ in range(SIMS // RUNS_PER_TRIAL):
        cal = calibrate(model, rng)
        for _ in range(RUNS_PER_TRIAL):
            ratios.append(trial_floor(model, rng, cal) / cal)
    ratios.sort()
    n = len(ratios)
    return {"n": n, "at_1.00": round(sum(r < 1.005 for r in ratios) / n, 3),
            "median": round(ratios[n // 2], 3), "p90": round(ratios[int(n * .9)], 3),
            "share_gt_1.5": round(sum(r > 1.5 for r in ratios) / n, 3),
            "share_gt_2": round(sum(r > 2 for r in ratios) / n, 3)}


if __name__ == "__main__":
    rng = random.Random(20261113)
    models = [("gauss", s) for s in (0.0025, 0.005, 0.0075, 0.01, 0.015, 0.02, 0.03)]
    models += [("outlier", 0.004, p, d) for p in (0.02, 0.05, 0.1) for d in (0.05, 0.1, 0.2)]
    rows = []
    for m in models:
        rows.append({"model": ":".join(map(str, m)), **run(m, rng)})
    with open(os.path.join(OUT, "sim.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(r)
