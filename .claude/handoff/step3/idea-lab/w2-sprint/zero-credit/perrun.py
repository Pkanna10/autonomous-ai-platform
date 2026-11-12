import csv, json, os
from collections import defaultdict, Counter
OUT = os.path.dirname(os.path.abspath(__file__))
d = json.load(open(os.path.join(OUT, "analysis.json")))
q1 = list(csv.DictReader(open(os.path.join(OUT, "q1_left_out.csv"))))
q2 = list(csv.DictReader(open(os.path.join(OUT, "q2_rounds.csv"))))
q3 = {(r["run"], r["repo"]): r for r in csv.DictReader(open(os.path.join(OUT, "q3_floors.csv")))}
# left-out conflict judged a semantic repeat of its blocker (read from the diffs)
R_BLOCKED = set("ba41d52e 38624877 583a8791 7f3a28a8 871eb2e8 c0942a3b 602c5ed0 727e71ef 41a38238 63e9aa5b d148dfa5 22e1332d 0e1d273b 43dcf9dd a462ce03 b2ca1fda 1a05c88f f0b74389 91d32316 5728b2e7 47bb88d1".split())
SOURCE = {("43145496896", "mistune"): "fallback (inferred d11a38da alone)",
          ("43107418692", "tomli"): "greedy or fallback (cannot tell)",
          ("43100257776", "tomli"): "greedy (1 kept)",
          ("43085626757", "markdown"): "greedy (inferred: applied keep is not the fallback pick)"}
rows = []
runs = [(r["arm"], r["run"], r["repo"], r["kept"], r["applied"], len(r["order"]), r["holds"]) for r in d["runs"]]
runs += [(s["arm"], s["run"], s["repo"], s["kept"], s["applied"], None, s["holds"]) for s in d["sv"]]
for arm, run, repo, kept, applied, delivered, holds in runs:
    lo = [x for x in q1 if x["run"] == run and x["repo"] == repo]
    c = Counter(x["reason"] for x in lo)
    rr = sorted((x for x in q2 if x["run"] == run and x["repo"] == repo), key=lambda x: int(x["round"]))
    f = q3[(run, repo)]
    rows.append({"arm": arm, "run": run, "repo": repo, "kept": kept, "applied_row": applied,
                 "delivered": "n/a (no kept_diffs)" if delivered is None else delivered,
                 "left_out": kept - (applied if delivered is None else delivered),
                 "a_conflict": c.get("a_conflict", 0),
                 "a_of_which_repeat_of_blocker": sum(x["trial"] in R_BLOCKED for x in lo if x["reason"] == "a_conflict"),
                 "b_retest": c.get("b_retest_failed", 0), "c_repeat_nothing_left": 0,
                 "d_cannot_tell": (kept - applied) if delivered is None else 0,
                 "kept_per_round_raw": "/".join(x["kept_raw"] for x in rr),
                 "kept_per_round_unique": "/".join(x["unique"] for x in rr),
                 "later_round_R": "/".join(x["repeats"] or "-" for x in rr[1:]),
                 "later_round_O": "/".join(x["overlaps_only"] or "-" for x in rr[1:]),
                 "holds": holds, "run_gain_pct": f["run_gain_pct"], "run_floor_pct": f["run_floor_pct"],
                 "baseline_floor_pct_est": f["baseline_floor_min_pct"],
                 "baseline_floor_trials_at_it": f'{f["mode_count"]}/{f["n_floors"]}',
                 "floor_ratio": f["ratio_run_floor_to_baseline"],
                 "run_row_measure_is": SOURCE.get((run, repo), "greedy combination")})
with open(os.path.join(OUT, "per_run.csv"), "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
for r in rows:
    print("|".join(str(v) for v in r.values()))
print()
for arm in ("X2-0", "X2-D", "X2-P", "X2-F", "X2-SV"):
    rs = [r for r in rows if r["arm"] == arm]
    ratios = sorted(float(r["floor_ratio"]) for r in rs)
    above = [r for r in rs if float(r["floor_ratio"]) > 1.005]
    print(arm, "runs", len(rs), "floor>baseline", len(above), "median ratio", ratios[len(ratios)//2], "max", ratios[-1],
          "mean run floor", round(sum(float(r["run_floor_pct"]) for r in rs)/len(rs), 2),
          "mean baseline", round(sum(float(r["baseline_floor_pct_est"]) for r in rs)/len(rs), 2),
          "failed", sum(r["holds"] is False for r in rs),
          "failed&gain>base", sum(r["holds"] is False and float(r["run_gain_pct"]) > float(r["baseline_floor_pct_est"]) for r in rs),
          "a_R", sum(r["a_of_which_repeat_of_blocker"] for r in rs))
