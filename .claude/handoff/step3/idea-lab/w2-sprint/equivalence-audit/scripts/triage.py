"""Triage every diff with differences: reproduce, classify, minimise.

python3 -I triage.py AUDIT_DIR LIB [SAMPLE=25] [MINIMISE=2]
For each diff in out/fuzz-<lib>.json with differences: start fresh base and
patched workers (runner.py serve, under `unshare -rn`), re-evaluate up to
SAMPLE differing inputs (smallest first), classify each, and ddmin-minimise
the MINIMISE smallest reproducible ones (<= 800 oracle calls each; the
predicate keeps the original fault kind). Writes out/triage-<lib>.json.
"""
import ast
import json
import os
import select
import subprocess
import sys

A, LIB = sys.argv[1], sys.argv[2]
SAMPLE = int(sys.argv[3]) if len(sys.argv) > 3 else 25
MINIM = int(sys.argv[4]) if len(sys.argv) > 4 else 2
HERE = os.path.dirname(os.path.abspath(__file__))


class Worker:
    def __init__(self, copy):
        self.copy = copy
        self.start()

    def start(self):
        self.p = subprocess.Popen(["unshare", "-rn", "--", "python3", "-I", "-B", os.path.join(HERE, "runner.py"),
                                   LIB, self.copy, "serve"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, bufsize=1)

    def ev(self, mode, s):
        self.p.stdin.write(json.dumps([mode, s]) + "\n")
        self.p.stdin.flush()
        r, _, _ = select.select([self.p.stdout], [], [], 60)
        if not r:
            self.p.kill()
            self.start()
            return ["hang", "worker hang"]
        line = self.p.stdout.readline()
        if not line:
            self.start()
            return ["crash", "worker died"]
        return json.loads(line)

    def close(self):
        self.p.kill()


def norm_ws(s):
    return "".join(s.split())


def classify(mode, b, p):
    """Return (kind, detail). b, p are [status, serialised]."""
    bs, ps = b[0], p[0]
    if b == p:
        return "same", ""
    if "timeout" in (bs, ps) or "hang" in (bs, ps) or "crash" in (bs, ps):
        return "hang or crash", f"{bs}->{ps}"
    if LIB == "sqlparse":
        bp, pp = ast.literal_eval(b[1]), ast.literal_eval(p[1])
        names = ["format", "parse", "split"]
        parts = [n for n, x, y in zip(names, bp, pp) if x != y]
        kinds = []
        for n, x, y in zip(names, bp, pp):
            if x == y:
                continue
            if x[0] == "ok" and y[0] == "ok":
                kinds.append(text_kind(repr(x[1]), repr(y[1])))
            elif x[0] == "ok":
                kinds.append("rejects valid input")
            elif y[0] == "ok":
                kinds.append("accepts invalid input")
            else:
                kinds.append("different exception")
        return kinds[0], "parts=" + ",".join(parts) + " kinds=" + ",".join(kinds)
    if bs == "ok" and ps == "ok":
        if LIB == "tomli":
            bv, bt = b[1].split("\n", 1)
            pv, pt = p[1].split("\n", 1)
            if bt != pt and (bv == pv or norm_types(bv) == norm_types(pv)):
                return "type change", ""
            if bt != pt:
                return "wrong output", "value and types differ"
            return "wrong output", ""
        return text_kind(b[1], p[1]), ""
    if bs == "ok":
        return "rejects valid input", p[1]
    if ps == "ok":
        return "accepts invalid input", b[1]
    return "different exception", f"{b[1]} -> {p[1]}"


def norm_types(v):
    return v.replace("(", "[").replace(")", "]").replace(",]", "]")


def text_kind(x, y):
    if norm_ws(x) == norm_ws(y):
        return "whitespace or formatting"
    if sorted(x) == sorted(y):
        return "ordering"
    return "wrong output"


def ddmin(s, pred, budget):
    calls = [0]

    def test(c):
        calls[0] += 1
        return pred(c)

    for unit in ("line", "char"):
        items = s.splitlines(True) if unit == "line" else list(s)
        n = 2
        while len(items) >= 2 and calls[0] < budget:
            chunk = max(1, len(items) // n)
            reduced = False
            for i in range(0, len(items), chunk):
                cand = items[:i] + items[i + chunk:]
                if calls[0] >= budget:
                    break
                if test("".join(cand)):
                    items, n, reduced = cand, max(n - 1, 2), True
                    break
            if not reduced:
                if chunk == 1:
                    break
                n = min(len(items), n * 2)
        s = "".join(items)
    return s, calls[0]


def main():
    fz = json.load(open(os.path.join(A, "out", f"fuzz-{LIB}.json")))
    corpus = json.load(open(os.path.join(A, "out", f"corpus-{LIB}.json")))
    diffs = {u["sha"][:12]: u for u in json.load(open(os.path.join(A, "out/diffs.json"))) if u["lib"] == LIB}
    outf = os.path.join(A, "out", f"triage-{LIB}.json")
    out = json.load(open(outf)) if os.path.exists(outf) else {}
    base = Worker(os.path.join(A, "work", LIB, "base"))
    for key, r in sorted(fz.items()):
        if key.startswith("_") or key in out or not r.get("diff_idx"):
            continue
        pw = Worker(diffs[key]["dir"])
        idx = sorted(r["diff_idx"], key=lambda i: len(corpus[i][1]))[:SAMPLE]
        samples, kinds = [], {}
        for i in idx:
            mode, s = corpus[i]
            b, p = base.ev(mode, s), pw.ev(mode, s)
            k, det = classify(mode, b, p)
            if k == "same":
                k = "not reproduced fresh (state-dependent)"
            kinds[k] = kinds.get(k, 0) + 1
            samples.append({"i": i, "mode": mode, "kind": k, "detail": det[:200],
                            "base_status": b[0], "patched_status": p[0], "input": s})
        mins = []
        for smp in [x for x in samples if not x["kind"].startswith("not reproduced")][:MINIM]:
            mode, want = smp["mode"], smp["kind"]

            def pred(c, mode=mode, want=want):
                b, p = base.ev(mode, c), pw.ev(mode, c)
                return classify(mode, b, p)[0] == want

            m, calls = ddmin(smp["input"], pred, 800)
            b, p = base.ev(mode, m), pw.ev(mode, m)
            k, det = classify(mode, b, p)
            mins.append({"mode": mode, "kind": k, "detail": det[:200], "input": m, "calls": calls,
                         "base": b[1][:600], "patched": p[1][:600],
                         "only_invalid": b[0] != "ok" if LIB in ("tomli", "sqlparse") else None})
        pw.close()
        out[key] = {"n_diff": len(r["diff_idx"]), "n": r["n"], "sampled": len(idx), "kinds": kinds,
                    "status_pairs": {sp: r["status_pairs"].count(sp) for sp in set(r["status_pairs"])},
                    "minimised": mins, "samples": [{k: v for k, v in x.items() if k != "input"} | {"input": x["input"][:300]} for x in samples[:5]]}
        json.dump(out, open(outf, "w"), indent=1)
        print(LIB, key, out[key]["n_diff"], kinds, [repr(m["input"])[:80] for m in mins], flush=True)
    base.close()


if __name__ == "__main__":
    main()
