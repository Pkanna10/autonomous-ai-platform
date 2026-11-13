"""Calibrate the tomli harness on s3-equivalence's planted mutants M1-M9.

python3 -I calibrate.py AUDIT_DIR S3_DIR
Each mutant (a full tomli copy) runs runner.py under `unshare -rn` on the
audit's fixed tomli corpus; prints differences against the base hashes.
"""
import json, os, subprocess, sys
A, S3 = sys.argv[1], sys.argv[2]
HERE = os.path.dirname(os.path.abspath(__file__))
base = json.load(open(os.path.join(A, "out", "hashes-tomli-base.json")))
for m in ["M1", "M2", "M3", "M4", "M7", "M8", "M9", "fast"]:
    out = os.path.join(A, "out", f"calib-{m}.json")
    subprocess.run(["unshare", "-rn", "--", "python3", "-I", "-B", os.path.join(HERE, "runner.py"), "tomli",
                    os.path.join(S3, f"tomli-{m}"), "batch", os.path.join(A, "out", "corpus-tomli.json"), out],
                   check=True, timeout=900)
    h = json.load(open(out))
    d = sum(x != y for x, y in zip(base["hashes"], h["hashes"]))
    print(m, "differences", d, "of", h["n"])
