"""Score the calibration mutants with the engine's two frozen oracles.

python3 -I frozen_oracles.py AUDIT_DIR VENV_PYTHON
(1) Workload fingerprint: the frozen workload (tests/fixtures/live_oss/workloads/<lib>.py
    from the main repo, read only) is copied to <copy>/benchmarks/ and run; its
    stdout digest is compared with the base's (the EquivalenceJudge's input).
(2) Test suite: the manifest's test_command, on a copy of the tag checkout's
    tests with the mutant package swapped in, run with VENV_PYTHON (pytest
    lives there; unittest for tomli). Pass means exit code 0.
Everything runs under `unshare -rn`, -B, with a 900 s timeout. Writes out/frozen-oracles.json.
"""
import json
import os
import shutil
import subprocess
import sys

A, PY = sys.argv[1], sys.argv[2]
WL = "/home/user/autonomous-ai-platform/services/python_agents/tests/fixtures/live_oss/workloads"
PKG = {"tomli": "src/tomli", "sqlparse": "sqlparse", "mistune": "src/mistune", "markdown": "markdown"}
TESTS = {"tomli": ["-m", "unittest", "discover", "-s", "tests", "-t", "."],
         "sqlparse": ["-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts=", "tests"],
         "mistune": ["-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts=", "tests"],
         "markdown": ["-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts=",
                      "tests/test_syntax/blocks", "tests/test_syntax/inline"]}
S3 = os.path.join(A, "..", "r3", "work", "s3-equivalence")


def env(root):
    e = {"PATH": "/usr/bin:/bin", "HOME": os.path.join(A, "work", "home"), "PYTHONDONTWRITEBYTECODE": "1",
         "PYTHONHASHSEED": "0", "PYTHONPATH": root}
    os.makedirs(e["HOME"], exist_ok=True)
    return e


def fingerprint(lib, copy):
    b = os.path.join(copy, "benchmarks")
    os.makedirs(b, exist_ok=True)
    shutil.copy(os.path.join(WL, f"{lib}.py"), os.path.join(b, f"bench_{lib}.py"))
    root = os.path.join(copy, "src") if lib in ("tomli", "mistune") else copy
    p = subprocess.run(["unshare", "-rn", "--", "python3", "-B", os.path.join(b, f"bench_{lib}.py")],
                       capture_output=True, text=True, timeout=900, env=env(root), cwd=copy)
    shutil.rmtree(b)
    return p.stdout.strip() if p.returncode == 0 else "ERR " + p.stderr[-200:]


def suite(lib, copy):
    d = os.path.join(A, "work", "suite", lib)
    if os.path.exists(d):
        shutil.rmtree(d)
    shutil.copytree(os.path.join(A, "libs", lib), d, ignore=shutil.ignore_patterns(".git"))
    shutil.rmtree(os.path.join(d, PKG[lib]))
    shutil.copytree(os.path.join(copy, PKG[lib]), os.path.join(d, PKG[lib]))
    root = os.path.join(d, "src") if lib in ("tomli", "mistune") else d
    p = subprocess.run(["unshare", "-rn", "--", PY, "-B", *TESTS[lib]], capture_output=True, text=True,
                       timeout=900, env=env(root), cwd=d)
    return p.returncode, (p.stdout + p.stderr).strip().splitlines()[-1:]


muts = json.load(open(os.path.join(A, "out", "calib-mutants.json")))
res = {}
for lib in ["mistune", "markdown", "sqlparse", "tomli"]:
    base = os.path.join(A, "work", lib, "base")
    bfp = fingerprint(lib, base)
    brc, btail = suite(lib, base)
    res[lib + " base"] = {"fingerprint": bfp, "suite_rc": brc, "suite_tail": btail}
    print(lib, "base", bfp[:60], brc, btail, flush=True)
    names = [n for n, m in muts.items() if m["lib"] == lib]
    copies = [(n, os.path.join(A, "work", lib, "mut-" + n.split()[0])) for n in names]
    if lib == "tomli":
        copies = [(m, os.path.join(S3, f"tomli-{m}")) for m in ["M1", "M2", "M3", "M4", "M7", "M8", "M9"]]
    for n, c in copies:
        if lib == "tomli":  # s3's mutants are full copies; use a package-only temp copy
            t = os.path.join(A, "work", "tomli", "s3-" + n)
            if not os.path.exists(t):
                shutil.copytree(os.path.join(c, "src", "tomli"), os.path.join(t, "src", "tomli"))
            c = t
        fp = fingerprint(lib, c)
        rc, tail = suite(lib, c)
        res[n] = {"lib": lib, "fingerprint_killed": fp != bfp, "suite_killed": rc != 0, "suite_tail": tail}
        print(lib, n, "fingerprint_killed", fp != bfp, "suite_killed", rc != 0, tail, flush=True)
json.dump(res, open(os.path.join(A, "out", "frozen-oracles.json"), "w"), indent=1)
