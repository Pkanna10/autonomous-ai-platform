"""Inventory of archived keeps and delivered patches (X2-SV excluded).

python3 -I inventory.py LIVE_DIR OUT_JSON
Reads ideas-x2-*.jsonl, joins run rows to hypothesis rows, resolves files.
"""
import glob, json, os, sys

LIBS = {"sqlparse", "tomli", "mistune", "markdown"}
live, out = sys.argv[1], sys.argv[2]
runs = []
for f in sorted(glob.glob(os.path.join(live, "ideas-x2-*.jsonl"))):
    tag = os.path.basename(f)[len("ideas-x2-"):-len(".jsonl")]
    if tag.startswith("X2-SV"):
        continue
    rows = [json.loads(l) for l in open(f)]
    hyps = {}
    for r in rows:
        if r["experiment"] == "ideas-x2-hypothesis":
            hyps[(r["repo"], r["hypothesis_id"])] = r
    for r in rows:
        if r["experiment"] != "ideas-x2-run" or r["repo"] not in LIBS:
            continue
        pdir = os.path.join(live, "patches-" + tag)
        def res(p):
            if not p:
                return None
            q = os.path.join(pdir, p.split("live-patches/", 1)[1])
            return q if os.path.exists(q) else "MISSING:" + q
        keeps = []
        for k in r.get("kept_diffs") or []:
            h = hyps.get((r["repo"], k.get("hypothesis_id")), {})
            keeps.append({
                "trial_id": k.get("trial_id"), "hypothesis_id": k.get("hypothesis_id"),
                "title": h.get("title"), "gain_pct": h.get("gain_pct"), "verdict": h.get("verdict"),
                "compound": h.get("compound"), "lane": h.get("lane"),
                "applied": k.get("applied"), "error": k.get("error"),
                "truncated": k.get("truncated"), "file": res(k.get("file")),
                "base_commit": k.get("base_commit"),
            })
        dp = r.get("delivered_patch") or {}
        runs.append({
            "run": tag, "repo": r["repo"], "base_commit": r.get("base_commit"),
            "gain_pct": r.get("gain_pct"), "delivered": r.get("delivered"), "holds": r.get("holds"),
            "delivered_patch": res(dp.get("file")), "applied_trial_ids": dp.get("applied_trial_ids"),
            "delivered_patch_note": r.get("delivered_patch_note"), "kept_diffs_note": r.get("kept_diffs_note"),
            "patch_truncated": dp.get("truncated"), "keeps": keeps,
        })
json.dump(runs, open(out, "w"), indent=1)
import collections
c = collections.Counter(); bc = collections.defaultdict(set)
for r in runs:
    bc[r["repo"]].add(r["base_commit"])
    c[(r["repo"], "runs")] += 1
    c[(r["repo"], "delivered_patch_files")] += bool(r["delivered_patch"] and not r["delivered_patch"].startswith("MISSING"))
    for k in r["keeps"]:
        c[(r["repo"], "keeps")] += 1
        c[(r["repo"], "keep_files")] += bool(k["file"] and not k["file"].startswith("MISSING"))
        c[(r["repo"], "keep_applied_false")] += k["applied"] is False
        c[(r["repo"], "keep_truncated")] += bool(k["truncated"])
for lib in sorted(LIBS):
    print(lib, sorted(bc[lib]), {k[1]: v for k, v in c.items() if k[0] == lib})
for r in runs:
    if r["delivered_patch_note"] or r["kept_diffs_note"] or not r["delivered_patch"]:
        print(r["run"], r["repo"], r["delivered_patch_note"], r["kept_diffs_note"])
    for k in r["keeps"]:
        if k["applied"] is False or (k["file"] or "").startswith("MISSING") or not k["file"]:
            print("  ", r["run"], r["repo"], k["trial_id"], k["applied"], k["error"], k["file"])
