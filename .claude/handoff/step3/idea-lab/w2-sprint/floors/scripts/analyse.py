"""Trial and combine floors against the calibrated baseline floor.

Usage: python3 -I analyse.py <out-dir>   (reads trials.csv, runs.csv from load.py)
Writes ratios_by_split.csv, combine_ratios.csv, q3_between.csv, q3_list.csv,
gain_above_base_rejected.csv, run_clusters.csv and prints the tables.
"""

import csv
import math
import os
import statistics as st
import sys

OUT = sys.argv[1]
T = list(csv.DictReader(open(os.path.join(OUT, "trials.csv"))))
R = list(csv.DictReader(open(os.path.join(OUT, "runs.csv"))))


def f(x):
    return None if x in ("", "None", None) else float(x)


for t in T:
    t["floor"], t["gain"] = f(t["floor"]), f(t["gain"])
    rec, prox, quiet = f(t["calib_recorded"]), f(t["calib_proxy_min"]), f(t["calib_quiet"])
    t["base_run"] = rec if rec is not None else prox      # the run's own calibration
    t["base_quiet"] = rec if rec is not None else quiet   # the brief's choice
    t["base_quiet_only"] = quiet
    t["base_src"] = "recorded" if rec is not None else "proxy"
    for k in ("index", "round", "case_position", "cases_in_dispatch", "index_in_round"):
        t[k] = int(t[k])
    t["elapsed_before_s"] = float(t["elapsed_before_s"])
T = [t for t in T if t["floor"] is not None]


def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return float("nan")
    k = (len(xs) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def dist(xs):
    return {"n": len(xs), "median": round(pct(xs, .5), 3), "p75": round(pct(xs, .75), 3),
            "p90": round(pct(xs, .9), 3), "max": round(max(xs), 3) if xs else None,
            "at_1.00": sum(1 for x in xs if x < 1.005),
            "gt_1.5": sum(1 for x in xs if x > 1.5), "gt_2": sum(1 for x in xs if x > 2.0),
            "share_gt_1.5": round(sum(1 for x in xs if x > 1.5) / len(xs), 3) if xs else None}


def splits():
    out = []
    keys = [
        ("all", lambda t: "all"),
        ("batch", lambda t: t["batch"]),
        ("dispatch_kind", lambda t: "one-run" if t["cases_in_dispatch"] == 1 else "multi-run"),
        ("case_position", lambda t: f"{t['case_position']} of {t['cases_in_dispatch']}"),
        ("case_position_any", lambda t: "first" if t["case_position"] == 1 else "later"),
        ("round", lambda t: f"round {t['round']}"),
        ("index_bucket", lambda t: "1-3" if t["index"] <= 3 else "4-6" if t["index"] <= 6 else "7-10" if t["index"] <= 10 else "11+"),
        ("index_in_round", lambda t: "1" if t["index_in_round"] == 1 else "2-3" if t["index_in_round"] <= 3 else "4+"),
        ("elapsed_before", lambda t: "0" if t["elapsed_before_s"] == 0 else "<1200 s" if t["elapsed_before_s"] < 1200 else ">=1200 s"),
        ("arm", lambda t: t["arm"]),
        ("library", lambda t: t["library"]),
        ("verdict", lambda t: t["verdict"]),
        ("base_src", lambda t: t["base_src"]),
    ]
    for base in ("base_run", "base_quiet"):
        for name, key in keys:
            groups = {}
            for t in T:
                groups.setdefault(key(t), []).append(t["floor"] / t[base])
            for g in sorted(groups):
                out.append({"against": base, "split": name, "group": g, **dist(groups[g])})
    return out


def combine():
    rows = []
    for r in R:
        rec, prox, quiet, fl = f(r["calib_recorded"]), f(r["calib_proxy_min"]), f(r["calib_quiet"]), f(r["combine_floor"])
        base_run = rec if rec is not None else prox
        if fl is None or fl == 0:
            rows.append({**{k: r[k] for k in ("arm", "dispatch", "library", "batch", "case_position", "cases_in_dispatch")},
                         "combine_floor": fl, "note": "no combine measured"})
            continue
        rows.append({**{k: r[k] for k in ("arm", "dispatch", "library", "batch", "case_position", "cases_in_dispatch")},
                     "combine_floor": round(fl, 3), "combine_gain": r["combine_gain"], "holds": r["holds"],
                     "base_run": round(base_run, 3), "base_quiet": quiet if rec is None else rec,
                     "ratio_run": round(fl / base_run, 3), "ratio_quiet": round(fl / (quiet if rec is None else rec), 3),
                     "ratio_quiet_only": round(fl / quiet, 3), "note": ""})
    return rows


def q3():
    """Gain above the baseline floor, below the trial's own floor."""
    lines, between, rejected = [], {}, []
    for t in T:
        g, fl = t["gain"], t["floor"]
        for base in ("base_run", "base_quiet"):
            b = t[base]
            key = (base, t["arm"], t["library"])
            c = between.setdefault(key, {"against": base, "arm": t["arm"], "library": t["library"],
                                         "trials": 0, "inconclusive": 0,
                                         "inc_between": 0, "inc_above_own": 0, "inc_below_base": 0,
                                         "reject_gain_above_base": 0, "keep": 0})
            c["trials"] += 1
            if t["verdict"] == "keep":
                c["keep"] += 1
            if t["verdict"] == "inconclusive":
                c["inconclusive"] += 1
                if g > fl:
                    c["inc_above_own"] += 1   # first look cleared: did not confirm
                elif g > b:
                    c["inc_between"] += 1
                    if base == "base_run":
                        lines.append({k: t[k] for k in ("arm", "dispatch", "library", "round", "index", "hypothesis_id", "lane", "gain", "floor", "base_run", "base_quiet_only")})
                else:
                    c["inc_below_base"] += 1
            if t["verdict"] == "reject" and g is not None and g > b:
                c["reject_gain_above_base"] += 1
                if base == "base_run":
                    rejected.append({k: t[k] for k in ("arm", "dispatch", "library", "round", "index", "hypothesis_id", "lane", "gain", "floor", "base_run")})
    return list(between.values()), lines, rejected


def clusters():
    """Per run: share of trials above 1.5x its own calibration, max ratio."""
    out = []
    for r in R:
        mine = [t for t in T if t["dispatch"] == r["dispatch"] and t["library"] == r["library"]]
        xs = [t["floor"] / t["base_run"] for t in mine]
        out.append({"arm": r["arm"], "dispatch": r["dispatch"], "library": r["library"],
                    "case_position": r["case_position"], "cases": r["cases_in_dispatch"],
                    "base_run": round(mine[0]["base_run"], 3) if mine else None,
                    "trials": len(xs), "gt_1.5": sum(1 for x in xs if x > 1.5),
                    "median_ratio": round(pct(xs, .5), 3) if xs else None,
                    "max_ratio": round(max(xs), 3) if xs else None})
    return out


def write(name, rows):
    if not rows:
        return
    fields = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with open(os.path.join(OUT, name), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def table(rows, cols):
    print(" | ".join(cols))
    for r in rows:
        print(" | ".join(str(r.get(c, "")) for c in cols))


if __name__ == "__main__":
    s = splits()
    write("ratios_by_split.csv", s)
    table(s, ["against", "split", "group", "n", "median", "p75", "p90", "max", "at_1.00", "gt_1.5", "gt_2", "share_gt_1.5"])
    c = combine()
    write("combine_ratios.csv", c)
    cr = [x for x in c if not x["note"]]
    print("\ncombine vs run calibration:", dist([x["ratio_run"] for x in cr]))
    print("combine vs quiet-or-recorded:", dist([x["ratio_quiet"] for x in cr]))
    for grp in ("one-run", "multi-run"):
        xs = [x["ratio_run"] for x in cr if (int(x["cases_in_dispatch"]) == 1) == (grp == "one-run")]
        print(" combine", grp, dist(xs))
    for pos in ("1", "2", "3"):
        xs = [x["ratio_run"] for x in cr if x["case_position"] == pos]
        if xs:
            print(" combine position", pos, dist(xs))
    print(" no combine:", [(x["dispatch"], x["library"]) for x in c if x["note"]])
    b, lines, rej = q3()
    write("q3_between.csv", b)
    write("q3_list.csv", lines)
    write("gain_above_base_rejected.csv", rej)
    print()
    table(b, ["against", "arm", "library", "trials", "keep", "inconclusive", "inc_between", "inc_above_own", "inc_below_base", "reject_gain_above_base"])
    for base in ("base_run", "base_quiet"):
        tot = {k: sum(x[k] for x in b if x["against"] == base) for k in ("trials", "keep", "inconclusive", "inc_between", "inc_above_own", "inc_below_base", "reject_gain_above_base")}
        print(base, tot)
    cl = clusters()
    write("run_clusters.csv", cl)
