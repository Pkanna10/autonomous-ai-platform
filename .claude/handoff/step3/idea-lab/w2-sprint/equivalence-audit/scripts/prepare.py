"""Materialise base and patched copies for every unique archived diff.

python3 -I prepare.py AUDIT_DIR
Reads out/inventory.json; libs/<lib> are clones checked out at the pinned tag.
Checks every diff's preimage blob ids against the tag tree (the engine's
base_commit is the tag plus its workload commit, not on GitHub).
Writes work/<lib>/base and work/<lib>/<sha12>/ (package dir only), out/diffs.json.
"""
import hashlib, json, os, re, shutil, subprocess, sys

A = sys.argv[1]
PKG = {"tomli": "src/tomli", "sqlparse": "sqlparse", "mistune": "src/mistune", "markdown": "markdown"}
inv = json.load(open(os.path.join(A, "out/inventory.json")))

def git(lib, *args):
    return subprocess.run(["git", "-C", os.path.join(A, "libs", lib), *args],
                          capture_output=True, text=True, timeout=60)

uniq = {}
for run in inv:
    lib = run["repo"]
    items = [("keep", k["file"], k) for k in run["keeps"]]
    if run["delivered_patch"]:
        items.append(("delivered", run["delivered_patch"], None))
    for kind, path, k in items:
        data = open(path, "rb").read()
        sha = hashlib.sha256(data).hexdigest()
        u = uniq.setdefault((lib, sha), {"lib": lib, "sha": sha, "bytes": len(data), "path": path, "uses": []})
        u["uses"].append({"kind": kind, "run": run["run"], "trial_id": k and k["trial_id"],
                          "title": k and k["title"], "gain_pct": k["gain_pct"] if k else run["gain_pct"],
                          "applied_in_combine": k and k["applied"]})

for lib, pkg in PKG.items():
    wd = os.path.join(A, "work", lib); os.makedirs(wd, exist_ok=True)
    base = os.path.join(wd, "base")
    if not os.path.exists(base):
        shutil.copytree(os.path.join(A, "libs", lib, pkg), os.path.join(base, pkg))

res = []
for (lib, sha), u in sorted(uniq.items()):
    text = open(u["path"], encoding="utf-8", errors="replace").read()
    files = re.findall(r"^diff --git a/(\S+) b/(\S+)", text, re.M)
    idx = re.findall(r"^index ([0-9a-f]+)\.\.([0-9a-f]+)", text, re.M)
    outside = [b for a, b in files if not b.startswith(PKG[lib] + "/")]
    pre_ok = True
    for (a, b), (old, new) in zip(files, idx):
        if set(old) == {"0"}:
            continue
        r = git(lib, "rev-parse", f"HEAD:{a}")
        if not r.stdout.strip().startswith(old):
            pre_ok = False
    dst = os.path.join(A, "work", lib, sha[:12])
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(os.path.join(A, "work", lib, "base"), dst)
    ap = subprocess.run(["git", "apply", "--whitespace=nowarn", os.path.abspath(u["path"])],
                        cwd=dst, capture_output=True, text=True, timeout=60)
    u.update({"files": [b for a, b in files], "outside_pkg": outside, "preimage_matches_tag": pre_ok,
              "applies": ap.returncode == 0, "apply_err": ap.stderr[-300:], "dir": dst})
    res.append(u)
json.dump(res, open(os.path.join(A, "out/diffs.json"), "w"), indent=1)
import collections
c = collections.Counter()
for u in res:
    c[(u["lib"], "unique")] += 1
    c[(u["lib"], "applies")] += u["applies"]
    c[(u["lib"], "preimage_ok")] += u["preimage_matches_tag"]
    c[(u["lib"], "outside_pkg")] += bool(u["outside_pkg"])
    for x in u["uses"]:
        c[(u["lib"], x["kind"] + "_uses")] += 1
for lib in PKG:
    print(lib, {k[1]: v for k, v in c.items() if k[0] == lib})
for u in res:
    if not u["applies"] or not u["preimage_matches_tag"] or u["outside_pkg"]:
        print("!!", u["lib"], u["sha"][:12], u["applies"], u["preimage_matches_tag"], u["outside_pkg"], u["apply_err"][:200])
