"""Differential fuzz of every unique archived diff against the base copy.

python3 -I fuzz_all.py AUDIT_DIR [--tag T --seed S] [LIB ...]
With --tag, a second corpus (own seed) is written under *-T names.
Fixed corpus per library (seed 20261113; counts in COUNTS). Each copy runs
runner.py in a subprocess under `unshare -rn` (the engine's network
namespace wrapper, without its launcher) with a 1800 s timeout, 2 at a time.
The base copy runs twice (a control: base against base must give 0
differences). Resumable: finished diffs are kept in out/fuzz-<lib>.json.
"""
import concurrent.futures as cf
import json
import os
import subprocess
import sys
import time

A = sys.argv[1]
ARGS = sys.argv[2:]
TAG, SEED = "", 20261113
if ARGS[:1] == ["--tag"]:
    TAG, SEED, ARGS = "-" + ARGS[1], int(ARGS[3]), ARGS[4:]
LIBS = ARGS or ["tomli", "sqlparse", "mistune", "markdown"]
COUNTS = {"tomli": 60000, "sqlparse": 2500, "mistune": 6000, "markdown": 5000}
HERE = os.path.dirname(os.path.abspath(__file__))
WRAP = ["unshare", "-rn", "--"]


def run_copy(lib, copy, corpus, out):
    t = time.time()
    p = subprocess.run(WRAP + ["python3", "-I", "-B", os.path.join(HERE, "runner.py"), lib, copy,
                               "batch", corpus, out], capture_output=True, text=True, timeout=1800)
    return p.returncode, p.stderr[-500:], time.time() - t


def main():
    diffs = json.load(open(os.path.join(A, "out/diffs.json")))
    for lib in LIBS:
        corpus = os.path.join(A, "out", f"corpus-{lib}{TAG}.json")
        if not os.path.exists(corpus):
            subprocess.run(["python3", "-I", os.path.join(HERE, "corpus.py"), lib, str(COUNTS[lib]),
                            str(SEED), corpus], check=True, timeout=600)
        resf = os.path.join(A, "out", f"fuzz-{lib}{TAG}.json")
        res = json.load(open(resf)) if os.path.exists(resf) else {}
        base_out = os.path.join(A, "out", f"hashes-{lib}-base{TAG}.json")
        if "_base" not in res:
            rc, err, dt = run_copy(lib, os.path.join(A, "work", lib, "base"), corpus, base_out)
            assert rc == 0, err
            rc2, err2, dt2 = run_copy(lib, os.path.join(A, "work", lib, "base"), corpus, base_out + ".2")
            b1, b2 = json.load(open(base_out)), json.load(open(base_out + ".2"))
            ctrl = sum(x != y for x, y in zip(b1["hashes"], b2["hashes"]))
            res["_base"] = {"seconds": dt, "control_diffs": ctrl, "n": b1["n"],
                            "valid": b1["status"].count("o"), "err": b1["status"].count("e"),
                            "timeout": b1["status"].count("t")}
            json.dump(res, open(resf, "w"), indent=1)
            print(lib, "base", res["_base"], flush=True)
        base = json.load(open(base_out))
        todo = [u for u in diffs if u["lib"] == lib and u["sha"][:12] not in res]

        def one(u):
            out = os.path.join(A, "out", f"hashes-{lib}-{u['sha'][:12]}{TAG}.json")
            try:
                rc, err, dt = run_copy(lib, u["dir"], corpus, out)
            except subprocess.TimeoutExpired:
                return u, {"rc": "timeout"}
            if rc != 0:
                return u, {"rc": rc, "stderr": err}
            h = json.load(open(out))
            idx = [i for i, (x, y) in enumerate(zip(base["hashes"], h["hashes"])) if x != y]
            os.remove(out)
            return u, {"rc": 0, "seconds": round(dt, 1), "n": h["n"], "diff_idx": idx,
                       "status_pairs": [base["status"][i] + h["status"][i] for i in idx]}

        with cf.ThreadPoolExecutor(2) as ex:
            for u, r in ex.map(one, todo):
                res[u["sha"][:12]] = r
                json.dump(res, open(resf, "w"), indent=1)
                print(lib, u["sha"][:12], r.get("rc"), r.get("seconds"), len(r.get("diff_idx", [])), flush=True)


if __name__ == "__main__":
    main()
