"""Load the X2 live archives into per-trial and per-run tables (read-only).

Usage: python3 -I load.py <live-dir> <out-dir>
Writes trials.csv and runs.csv to <out-dir>.
"""

import csv
import glob
import json
import os
import sys

LIVE, OUT = sys.argv[1], sys.argv[2]

# Quiet-runner calibrated floors (o62/combine-replay-43194422719.jsonl, kind=case)
QUIET = {"tomli": 3.5557, "mistune": 2.0, "sqlparse": 2.0, "markdown": 4.41}
QUIET_ALT = {"mistune": 2.72}  # the second mistune case (43145496896 tip)

# Which dispatches belong to which batch (task brief)
O61 = {"43145496896"} | {"43159144063", "43159147698", "43159151284", "43159154661",
                         "43159157891", "43159160974"}
O62 = {"43181006070", "43181010850"}


def batch(arm: str, dispatch: str) -> str:
    if dispatch in O62:
        return "O62"
    if arm == "X2-L" or dispatch in O61:
        return "O61"
    return "O59-sprint"


def main() -> None:
    trials, runs = [], []
    files = sorted(glob.glob(os.path.join(LIVE, "ideas-x2-*.jsonl")))
    for f in files:
        name = os.path.basename(f)[len("ideas-x2-"):-len(".jsonl")]
        arm, dispatch = name.rsplit("-", 1)
        if arm == "X2-SV":
            continue
        rows = [json.loads(line) for line in open(f)]
        order = []  # case order in the dispatch = file order (verified in report)
        for r in rows:
            if r["repo"] not in order:
                order.append(r["repo"])
        run_rows = {r["repo"]: r for r in rows if r["experiment"] == "ideas-x2-run"}
        elapsed_before = {}
        acc = 0.0
        for repo in order:
            elapsed_before[repo] = acc
            acc += run_rows[repo]["seconds_measured"]
        for repo in order:
            hyp = [r for r in rows if r["experiment"] == "ideas-x2-hypothesis" and r["repo"] == repo]
            floors = [h["floor_pct"] for h in hyp if h["floor_pct"] is not None]
            proxy = min(floors) if floors else None
            run = run_rows[repo]
            calib = run.get("baseline_floor_pct")
            rounds_seen = [h["round"] for h in hyp]
            monotone = all(a <= b for a, b in zip(rounds_seen, rounds_seen[1:]))
            common = {
                "arm": arm, "dispatch": dispatch, "batch": batch(arm, dispatch),
                "library": repo, "cases_in_dispatch": len(order),
                "case_position": order.index(repo) + 1,
                "elapsed_before_s": round(elapsed_before[repo], 1),
                "calib_recorded": calib, "calib_proxy_min": proxy,
                "calib_quiet": QUIET[repo],
            }
            runs.append({**common, "combine_floor": run["floor_pct"],
                         "combine_gain": run["gain_pct"], "holds": run["holds"],
                         "seconds_measured": run["seconds_measured"],
                         "trials": len(hyp), "rounds_monotone": monotone,
                         "n_at_proxy": sum(1 for x in floors if proxy is not None and abs(x - proxy) < 1e-9)})
            for i, h in enumerate(hyp):
                trials.append({**common, "index": i + 1, "round": h["round"],
                               "index_in_round": sum(1 for g in hyp[:i] if g["round"] == h["round"]) + 1,
                               "lane": h["lane"], "compound": h["compound"],
                               "verdict": h["verdict"], "gain": h["gain_pct"], "floor": h["floor_pct"],
                               "hypothesis_id": h["hypothesis_id"]})
    for name, table in (("trials.csv", trials), ("runs.csv", runs)):
        with open(os.path.join(OUT, name), "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(table[0]))
            w.writeheader()
            w.writerows(table)
    print(f"{len(runs)} runs, {len(trials)} trial rows")


if __name__ == "__main__":
    main()
