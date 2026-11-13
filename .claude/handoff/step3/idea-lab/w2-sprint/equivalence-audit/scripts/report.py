"""Aggregate the audit per library.

python3 -I report.py AUDIT_DIR
Inputs: out/inventory.json, out/diffs.json, out/fuzz-<lib>.json (+ -v2),
out/triage-<lib>.json (when present). Writes out/report.json and prints the
per-library table, the per-diff list of non-equivalent diffs with their
titles and gains, and the delivered-gain sums.
"""
import collections
import json
import os
import sys

A = sys.argv[1]
LIBS = ["sqlparse", "tomli", "mistune", "markdown"]
inv = json.load(open(os.path.join(A, "out/inventory.json")))
diffs = json.load(open(os.path.join(A, "out/diffs.json")))
import hashlib
by_sha = {u["sha"]: u for u in diffs}


class _ByPath(dict):
    def __missing__(self, path):
        self[path] = by_sha[hashlib.sha256(open(path, "rb").read()).hexdigest()]
        return self[path]


by_path = _ByPath()
rep = {}
for lib in LIBS:
    fz = json.load(open(os.path.join(A, "out", f"fuzz-{lib}.json")))
    f2 = os.path.join(A, "out", f"fuzz-{lib}-v2.json")
    fz2 = json.load(open(f2)) if os.path.exists(f2) else {}
    tf = os.path.join(A, "out", f"triage-{lib}.json")
    tr = json.load(open(tf)) if os.path.exists(tf) else {}
    nd = {k: len(v.get("diff_idx", [])) + len(fz2.get(k, {}).get("diff_idx", []))
          for k, v in fz.items() if not k.startswith("_")}
    failed = {k: v for f in (fz, fz2) for k, v in f.items() if not k.startswith("_") and v.get("rc") != 0}
    v2_missing = [k for k in nd if fz2 and k not in fz2]

    def differs(path):
        return nd.get(by_path[path]["sha"][:12], 0) > 0

    runs = [r for r in inv if r["repo"] == lib]
    keeps = [(r, k) for r in runs for k in r["keeps"]]
    uniq_keep = {by_path[k["file"]]["sha"] for _, k in keeps}
    bad_keeps = [(r, k) for r, k in keeps if differs(k["file"])]
    deliv = [r for r in runs if r["delivered_patch"]]
    bad_deliv = [r for r in deliv if differs(r["delivered_patch"])]
    rest = []
    for r in deliv:
        applied = set(r["applied_trial_ids"] or [])
        bad_applied = [k for k in r["keeps"] if k["trial_id"] in applied and differs(k["file"])]
        if bad_applied or differs(r["delivered_patch"]):
            rest.append((r, bad_applied))
    kinds = collections.Counter()
    examples = {}
    for key, t in tr.items():
        for k, c in t["kinds"].items():
            kinds[k] += c
        for m in t["minimised"]:
            examples.setdefault(m["kind"], (key, m))
    rep[lib] = {
        "runs": len(runs), "keep_uses": len(keeps), "unique_keep_diffs": len(uniq_keep),
        "keep_uses_differing": len(bad_keeps),
        "unique_keep_diffs_differing": len({by_path[k["file"]]["sha"] for _, k in bad_keeps}),
        "delivered": len(deliv), "delivered_differing": len(bad_deliv),
        "delivered_gain_sum_all": round(sum(r["gain_pct"] for r in deliv), 2),
        "delivered_gain_sum_patch_differs": round(sum(r["gain_pct"] for r in bad_deliv), 2),
        "delivered_gain_sum_rests_on_bad_keep_or_patch": round(sum(r["gain_pct"] for r, _ in rest), 2),
        "runs_resting": [{"run": r["run"], "gain_pct": round(r["gain_pct"], 2),
                          "patch_differs": differs(r["delivered_patch"]),
                          "bad_applied_keeps": [(k["title"], round(k["gain_pct"], 2)) for k in b]} for r, b in rest],
        "fuzz_failures": failed, "base": fz["_base"], "base_v2": fz2.get("_base"),
        "inputs_per_diff": fz["_base"]["n"] + (fz2["_base"]["n"] if fz2 else 0), "v2_missing": len(v2_missing),
        "cpu_seconds_per_diff_median": sorted(v["seconds"] for v in fz.values() if "seconds" in v)[len(nd) // 2],
        "kinds_sampled": dict(kinds),
        "bad_keeps": sorted({(by_path[k["file"]]["sha"][:12], k["title"], round(k["gain_pct"], 2), nd[by_path[k["file"]]["sha"][:12]])
                             for _, k in bad_keeps}, key=lambda x: -x[3]),
        "examples": {k: {"diff": key, "input": m["input"], "mode": m["mode"], "detail": m["detail"],
                         "only_invalid": m["only_invalid"], "base": m["base"][:300], "patched": m["patched"][:300]}
                     for k, (key, m) in examples.items()},
    }
json.dump(rep, open(os.path.join(A, "out/report.json"), "w"), indent=1)
print(f"{'lib':9} {'keeps':>5} {'uniq':>4} {'bad':>4} {'ubad':>4} {'deliv':>5} {'dbad':>4} {'gainΣ':>7} {'Σ patch':>7} {'Σ rests':>7}")
for lib, x in rep.items():
    print(f"{lib:9} {x['keep_uses']:5} {x['unique_keep_diffs']:4} {x['keep_uses_differing']:4} {x['unique_keep_diffs_differing']:4} "
          f"{x['delivered']:5} {x['delivered_differing']:4} {x['delivered_gain_sum_all']:7} {x['delivered_gain_sum_patch_differs']:7} "
          f"{x['delivered_gain_sum_rests_on_bad_keep_or_patch']:7}")
for lib, x in rep.items():
    print("==", lib, "inputs/diff", x["inputs_per_diff"], "v2_missing", x["v2_missing"], "median s/diff (pass 1)", x["cpu_seconds_per_diff_median"], "base", x["base"], x["base_v2"], "failures", x["fuzz_failures"], "kinds", x["kinds_sampled"])
    for b in x["bad_keeps"]:
        print("  keep", b)
    for r in x["runs_resting"]:
        print("  run", r)
    for k, e in x["examples"].items():
        print("  ex", k, e["diff"], e["mode"], repr(e["input"])[:120], "| only_invalid:", e["only_invalid"], "|", e["detail"][:100])
        print("     base:", repr(e["base"])[:200])
        print("     patch:", repr(e["patched"])[:200])
