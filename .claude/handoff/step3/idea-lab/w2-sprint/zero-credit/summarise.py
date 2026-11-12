"""Aggregate analysis.json + manual repeat labels into per-arm tables and CSVs."""
from __future__ import annotations

import csv
import json
import os
from collections import Counter, defaultdict

OUT = os.path.dirname(os.path.abspath(__file__))
ARMS = ("X2-0", "X2-D", "X2-P", "X2-F", "X2-SV")
d = json.load(open(os.path.join(OUT, "analysis.json")))
pairs = list(csv.DictReader(open(os.path.join(OUT, "pairs.csv"))))

# Cross-round labels by reading the diffs (R = same technique on the same
# code, incl. partial/identical hunks; O = different change, overlapping or
# conflicting hunks). (run, earlier trial, later trial, label)
L = """
43080309535 498a0beb 38624877 R
43085609944 7b16fe32 a2c3f6a5 O
43085609944 e1c4480a fde33722 O
43085616371 81e8b008 583a8791 R
43085616371 f4e5349e cdccc54d O
43085616371 160979cb cdccc54d O
43085616371 ffef99a1 620a549c O
43085616371 7dd3d89f 620a549c O
43093762527 dd15cc60 871eb2e8 R
43093762527 7f3a28a8 55198011 R
43093767768 a98578e4 bac29f6f O
43093767768 a7d5e305 bac29f6f O
43093767768 c61e038e 76c6f0e3 O
43085621843 1be83552 602c5ed0 R
43085626757 0a0480ff 727e71ef R
43085626757 69359be0 fa391c5a O
43085626757 69359be0 af0d2b9a R
43085626757 fa391c5a af0d2b9a O
43093773731 a56bbb30 41a38238 R
43093773731 a56bbb30 566222c8 O
43093773731 41a38238 566222c8 O
43093773731 63e9aa5b 593eb066 R
43093773731 63e9aa5b d148dfa5 R
43093773731 593eb066 d148dfa5 R
43093779047 22e1332d 43dcf9dd R
43093779047 cbb94c70 43dcf9dd R
43093779047 0e1d273b 43dcf9dd R
43093788927 0a89aff7 a462ce03 R
43093788927 70a8ceba a462ce03 O
43093788927 9f1d005d b2ca1fda R
43093788927 0877c618 d72e1215 O
43093788927 2fd8a385 d72e1215 O
43093788927 a45758fe d72e1215 O
43145496896 0bd966c3 9d892b37 O
43145496896 0bd966c3 1cd07e41 O
43145496896 9d892b37 1cd07e41 R
43145496896 b741a3ad f0efa548 R
43145496896 f0efa548 108c5afa O
43104071793 3f76eb69 aaaa1165 O
43100257776 79a41dd7 f6920514 O
43104077245 d9756e5f f0b74389 R
43104077245 c5d6a985 2185f97d O
43104077245 f7835134 495fe030 O
43107418692 99e8236f 37cd3024 O
43111359647 e55eb4d3 940bd4e1 O
43111359647 3244e98c 91d32316 R
43114988674 b0ec727b b47e9252 O
43114988674 aa4143a6 b47e9252 O
43114988674 5728b2e7 8e3adf6b R
43114992515 49935a11 2fd1059a O
43114992515 1b214663 cac59077 O
43114992515 47bb88d1 4e431e9e R
"""
labels = {}
for line in L.strip().splitlines():
    run, a, b, lab = line.split()
    labels[(run, a, b)] = lab

# every cross-round non-disjoint pair must carry a label, and vice versa
cross = {}
for p in pairs:
    ra, rb = int(p["a_round"]), int(p["b_round"])
    if ra == rb:
        continue
    early, late = (p["a"], p["b"]) if ra < rb else (p["b"], p["a"])
    nd = p["relation"] in ("conflict", "overlap_clean", "identical", "b_subset_of_a", "a_subset_of_b") or int(p["identical_hunks"]) > 0
    if nd:
        cross[(p["run"], early, late)] = p
missing = set(cross) - set(labels)
extra = set(labels) - set(cross)
assert not missing and not extra, (missing, extra)

# --- Q2 per run per round
q2 = []
for r in d["runs"]:
    rounds = r["rounds"]
    nrounds = max(int(k) for k in r["round_rows"])
    flagged_r, flagged_any = set(), set()
    for (run, a, b), lab in labels.items():
        if run != r["run"] or a not in rounds or b not in rounds:
            continue
        flagged_any.add(b)
        if lab == "R":
            flagged_r.add(b)
    for n in range(1, nrounds + 1):
        ks = [t for t, k in rounds.items() if k == n]
        q2.append({"arm": r["arm"], "run": r["run"], "repo": r["repo"], "round": n,
                   "kept_raw": len(ks), "round_row_kept": r["round_rows"].get(str(n), 0),
                   "repeats": sum(t in flagged_r for t in ks),
                   "overlaps_only": sum(t in flagged_any and t not in flagged_r for t in ks),
                   "unique": sum(t not in flagged_any for t in ks),
                   "unique_repeats_removed_only": sum(t not in flagged_r for t in ks),
                   "flagged": ";".join(t for t in ks if t in flagged_any)})
# SV proxy: later-round keep whose target path and line range overlaps an earlier keep's
for s in d["sv"]:
    keeps = s["keeps"]
    nrounds = max(int(k) for k in s["round_rows"])
    for n in range(1, nrounds + 1):
        ks = [k for k in keeps if k["round"] == n]
        fl = 0
        for k in ks:
            t = k["target"]
            if t is None:
                continue
            for e in keeps:
                if e["round"] < n and e["target"] and e["target"]["path"] == t["path"] and \
                        e["target"]["first"] <= t["last"] and t["first"] <= e["target"]["last"]:
                    fl += 1
                    break
        q2.append({"arm": s["arm"], "run": s["run"], "repo": s["repo"], "round": n,
                   "kept_raw": len(ks), "round_row_kept": s["round_rows"].get(str(n), 0),
                   "repeats": None, "overlaps_only": None, "unique": len(ks) - fl,
                   "unique_repeats_removed_only": None, "flagged": f"target-proxy:{fl}"})

with open(os.path.join(OUT, "q2_rounds.csv"), "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(q2[0]))
    w.writeheader()
    w.writerows(q2)
with open(os.path.join(OUT, "q2_cross_round_pairs.csv"), "w", newline="") as fh:
    cols = ["arm", "run", "repo", "earlier", "earlier_round", "earlier_applied", "later", "later_round",
            "later_applied", "label", "relation", "identical_hunks", "del_cov", "add_sim",
            "overlapping_hunks", "earlier_title", "later_title"]
    w = csv.DictWriter(fh, fieldnames=cols)
    w.writeheader()
    for (run, e, l), p in sorted(cross.items()):
        ea = p["a"] == e
        w.writerow({"arm": p["arm"], "run": run, "repo": p["repo"], "earlier": e,
                    "earlier_round": p["a_round"] if ea else p["b_round"],
                    "earlier_applied": p["a_applied"] if ea else p["b_applied"], "later": l,
                    "later_round": p["b_round"] if ea else p["a_round"],
                    "later_applied": p["b_applied"] if ea else p["a_applied"],
                    "label": labels[(run, e, l)], "relation": p["relation"],
                    "identical_hunks": p["identical_hunks"], "del_cov": p["del_cov"], "add_sim": p["add_sim"],
                    "overlapping_hunks": p["overlapping_hunks"][:300],
                    "earlier_title": p["a_title"] if ea else p["b_title"],
                    "later_title": p["b_title"] if ea else p["a_title"]})

# --- print aggregates
print("Q1 per arm")
q1 = list(csv.DictReader(open(os.path.join(OUT, "q1_left_out.csv"))))
for arm in ARMS:
    runs = [r for r in d["runs"] if r["arm"] == arm]
    sv = [s for s in d["sv"] if s["arm"] == arm]
    kept = sum(r["kept"] for r in runs) + sum(s["kept"] for s in sv)
    delivered = sum(len(r["order"]) for r in runs) + sum(s["applied"] for s in sv)
    row_applied = sum(r["applied"] for r in runs) + sum(s["applied"] for s in sv)
    c = Counter(x["reason"] for x in q1 if x["arm"] == arm)
    print(arm, "runs", len(runs) + len(sv), "kept", kept, "applied(row)", row_applied, "delivered", delivered,
          "left", kept - delivered, dict(c))
print("Q2 per arm, per round: raw / unique (repeats+overlaps removed) / repeats-only removed; per run")
for arm in ARMS:
    rows = [x for x in q2 if x["arm"] == arm]
    nr = len({x["run"] + x["repo"] for x in rows})
    for n in (1, 2, 3):
        rr = [x for x in rows if x["round"] == n]
        if not rr:
            continue
        raw = sum(x["kept_raw"] for x in rr)
        uni = sum(x["unique"] for x in rr)
        uro = sum(x["unique_repeats_removed_only"] or 0 for x in rr) if arm != "X2-SV" else None
        rep = sum(x["repeats"] or 0 for x in rr)
        ov = sum(x["overlaps_only"] or 0 for x in rr)
        print(arm, "round", n, "runs", nr, "with-round", len(rr), "raw", raw, f"({raw/nr:.2f}/run)", "unique", uni,
              f"({uni/nr:.2f}/run)", "repeat-only-removed", uro, "R", rep, "O", ov)
print("Q3")
for arm in ARMS:
    rows = [x for x in csv.DictReader(open(os.path.join(OUT, "q3_floors.csv"))) if x["arm"] == arm]
    print(arm, [(x["run"][-5:], x["repo"][:5], x["run_gain_pct"], x["run_floor_pct"], x["baseline_floor_min_pct"]) for x in rows])
