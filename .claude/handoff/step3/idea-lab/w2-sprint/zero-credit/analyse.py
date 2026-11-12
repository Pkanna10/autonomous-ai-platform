"""Read-only analysis of X2 sprint combine: kept vs applied, repeats, floors.

Method: every trial diff is against the run's base commit. Per (run, file) a
synthetic sparse base is built from the old side (context and '-' lines) of
every diff of that run (line numbers are exact; unknown lines are unique
placeholders). Each diff is applied to it exactly (no fuzz), and git
merge-file (3-way, same xdiff merge the combiner's merge-tree uses) replays
the greedy combine and the pairwise merges. Independently, changed old-line
ranges per hunk are compared (overlap or adjacency = textual conflict risk).
"""
from __future__ import annotations

import csv
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from itertools import combinations

LIVE = "/home/user/step3-emergence-r1/.claude/handoff/step3/idea-lab/w2-sprint/live"
OUT = os.path.dirname(os.path.abspath(__file__))
ARMS = ("X2-0", "X2-D", "X2-P", "X2-F", "X2-SV")
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")
TMP = tempfile.mkdtemp(dir=OUT, prefix="merge-")


def parse_diff(text: str) -> dict[str, list[dict]]:
    files: dict[str, list[dict]] = {}
    cur = None
    hunks: list[dict] | None = None
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("diff --git "):
            cur = None
        elif ln.startswith("--- "):
            old = ln[4:]
            new = lines[i + 1][4:]
            path = (new if new != "/dev/null" else old)
            path = path[2:] if path[:2] in ("a/", "b/") else path
            cur = path
            hunks = files.setdefault(cur, [])
            i += 2
            continue
        else:
            m = HUNK.match(ln)
            if m and hunks is not None:
                os_, ol, ns, nl, func = m.groups()
                h = {"os": int(os_), "ol": 1 if ol is None else int(ol),
                     "ns": int(ns), "nl": 1 if nl is None else int(nl),
                     "func": func.strip(), "lines": []}
                hunks.append(h)
                o = n = 0
                i += 1
                while i < len(lines) and (o < h["ol"] or n < h["nl"]):
                    l2 = lines[i]
                    if l2.startswith("\\"):
                        i += 1
                        continue
                    tag, body = (l2[:1] or " "), l2[1:]
                    h["lines"].append((tag, body))
                    if tag in " -":
                        o += 1
                    if tag in " +":
                        n += 1
                    i += 1
                while i < len(lines) and lines[i].startswith("\\"):
                    i += 1
                continue
        i += 1
    return files


def changed_ranges(h: dict) -> list[tuple[int, int, str]]:
    """Old-side ranges [a, b) of changed lines; a pure insertion is [p, p)."""
    out = []
    o = h["os"]
    start = None
    for tag, _ in h["lines"]:
        if tag == " ":
            if start is not None:
                out.append((start, o))
                start = None
            o += 1
        elif tag == "-":
            if start is None:
                start = o
            o += 1
        else:  # '+'
            if start is None:
                start = o
    if start is not None:
        out.append((start, o))
    # functions: nearest def/class line at or above the change in the hunk view
    res = []
    for a, b in out:
        res.append((a, b, func_at(h, a)))
    return res


DEF = re.compile(r"^\s*(?:async\s+)?(def|class)\s+(\w+)")


def func_at(h: dict, line: int) -> str:
    o = h["os"]
    name = None
    for tag, body in h["lines"]:
        if tag in " -":
            if o >= line and tag == "-":
                pass
            if o >= line + 1 and name is not None:
                break
            m = DEF.match(body)
            if m and o <= line:
                name = m.group(2)
            o += 1
    if name:
        return name
    m = DEF.search(h["func"])
    return m.group(2) if m else h["func"][:40]


def deleted(path: str, h: dict) -> set:
    o, out = h["os"], set()
    for t_, _ in h["lines"]:
        if t_ in " -":
            if t_ == "-":
                out.add((path, o))
            o += 1
    return out


def overlaps(r1: tuple[int, int], r2: tuple[int, int]) -> bool:
    """Changed old ranges overlap or touch (git treats adjacency as conflict)."""
    a1, b1 = r1
    a2, b2 = r2
    return a1 <= b2 and a2 <= b1


class Run:
    def __init__(self, arm: str, rid: str, row: dict, hyps: list[dict]):
        self.arm, self.rid, self.row, self.hyps = arm, rid, row, hyps
        self.repo = row["repo"]
        self.kd = row.get("kept_diffs") or []
        self.dp = row.get("delivered_patch")
        self.diffs: dict[str, dict] = {}
        self.texts: dict[str, str] = {}
        self.hyp_by_id = {h["hypothesis_id"]: h for h in hyps}
        for k in self.kd:
            p = self.path(k["file"])
            t = open(p).read()
            self.texts[k["trial_id"]] = t
            self.diffs[k["trial_id"]] = parse_diff(t)
        if self.dp:
            t = open(self.path(self.dp["file"])).read()
            self.texts["delivered"] = t
            self.diffs["delivered"] = parse_diff(t)
        self.build_base()

    def path(self, f: str) -> str:
        return os.path.join(LIVE, f"patches-{self.arm}-{self.rid}", f.split("live-patches/")[1])

    def build_base(self) -> None:
        self.base: dict[str, list[str]] = {}
        self.base_conflicts = []
        known: dict[str, dict[int, str]] = defaultdict(dict)
        for tid, files in self.diffs.items():
            for path, hunks in files.items():
                for h in hunks:
                    o = h["os"]
                    for tag, body in h["lines"]:
                        if tag in " -":
                            prev = known[path].get(o)
                            if prev is not None and prev != body:
                                self.base_conflicts.append((tid, path, o))
                            known[path][o] = body
                            o += 1
        for path, m in known.items():
            n = max(m) if m else 0
            self.base[path] = [m.get(i, f"\x01PH:{path}:{i}") for i in range(1, n + 1)]

    def apply(self, tid: str) -> dict[str, list[str]]:
        out = {p: list(v) for p, v in self.base.items()}
        for path, hunks in self.diffs[tid].items():
            src = self.base.get(path, [])
            res: list[str] = []
            pos = 1
            for h in hunks:
                start = h["os"] if h["ol"] else h["os"] + 1
                res.extend(src[pos - 1:start - 1])
                pos = start
                for tag, body in h["lines"]:
                    if tag in " -":
                        assert src[pos - 1] == body, (self.rid, tid, path, pos)
                        pos += 1
                    if tag in " +":
                        res.append(body)
            res.extend(src[pos - 1:])
            out[path] = res
        return out

    def merge(self, cur: dict[str, list[str]], other: dict[str, list[str]]):
        """3-way merge per file; returns (merged, conflicted paths)."""
        merged, conf = {}, []
        for path in self.base:
            b, c, o = self.base[path], cur[path], other[path]
            if o == b:
                merged[path] = c
                continue
            if c == b:
                merged[path] = o
                continue
            fs = []
            for name, data in (("c", c), ("b", b), ("o", o)):
                fp = os.path.join(TMP, name)
                with open(fp, "w") as fh:
                    fh.write("\n".join(data) + "\n")
                fs.append(fp)
            r = subprocess.run(["git", "merge-file", "-p", "-q", *fs],
                               capture_output=True, text=True)
            if r.returncode != 0:
                conf.append(path)
                merged[path] = c
            else:
                merged[path] = r.stdout[:-1].split("\n") if r.stdout else []
        return merged, conf


def load():
    runs: list[Run] = []
    sv_runs = []
    for f in sorted(glob.glob(os.path.join(LIVE, "ideas-x2-*.jsonl"))):
        base = os.path.basename(f)[len("ideas-x2-"):-len(".jsonl")]
        arm, rid = base.rsplit("-", 1)
        if arm not in ARMS:
            continue
        rows = [json.loads(line) for line in open(f)]
        for r in rows:
            if r["experiment"] != "ideas-x2-run":
                continue
            hyps = [h for h in rows if h["experiment"] == "ideas-x2-hypothesis" and h["repo"] == r["repo"]]
            rnds = [h for h in rows if h["experiment"] == "ideas-x2-round" and h["repo"] == r["repo"]]
            if r.get("kept_diffs"):
                run = Run(arm, rid, r, hyps)
                run.rounds = rnds
                runs.append(run)
            else:
                sv_runs.append((arm, rid, r, hyps, rnds))
    return runs, sv_runs


def main() -> None:
    runs, sv_runs = load()
    q1_rows, q2_rows, q3_rows, pair_rows = [], [], [], []
    for run in runs:
        assert not run.base_conflicts, run.base_conflicts
        kd = {k["trial_id"]: k for k in run.kd}
        hid = {k["trial_id"]: k["hypothesis_id"] for k in run.kd}
        rnd = {t: run.hyp_by_id[h]["round"] for t, h in hid.items()}
        gain = {t: run.hyp_by_id[h]["gain_pct"] for t, h in hid.items()}
        order = list(run.dp["applied_trial_ids"]) if run.dp else []
        flagged = [t for t, k in kd.items() if k["applied"]]
        assert set(order) == set(flagged), (run.rid, run.repo)
        ver = {t: run.apply(t) for t in kd}
        # replay greedy over the applied ones in order
        acc = {p: list(v) for p, v in run.base.items()}
        replay_ok = True
        for t in order:
            acc, conf = run.merge(acc, ver[t])
            if conf:
                replay_ok = False
        deliv_match = None
        if run.dp:
            deliv_match = run.apply("delivered") == acc
        left = [t for t in kd if t not in order]
        # pairwise relations between all keeps
        rel = {}
        for a, b in combinations(kd, 2):
            m, conf = run.merge(ver[a], ver[b])
            same = ver[a] == ver[b]
            b_in_a = not conf and m == ver[a]
            a_in_b = not conf and m == ver[b]
            # textual range overlap
            hunk_ov = []
            for path in set(run.diffs[a]) & set(run.diffs[b]):
                for ha in run.diffs[a][path]:
                    for hb in run.diffs[b][path]:
                        for ra in changed_ranges(ha):
                            for rb in changed_ranges(hb):
                                if overlaps(ra[:2], rb[:2]):
                                    hunk_ov.append(f"{path}:{ra[0]}-{ra[1]}({ra[2]})~{rb[0]}-{rb[1]}({rb[2]})")
            same_hunks = 0
            da, db, aa, ab = set(), set(), [], []
            for path in set(run.diffs[a]) & set(run.diffs[b]):
                for ha in run.diffs[a][path]:
                    for hb in run.diffs[b][path]:
                        if any(overlaps(x[:2], y[:2]) for x in changed_ranges(ha) for y in changed_ranges(hb)):
                            da |= deleted(path, ha); db |= deleted(path, hb)
                            aa += [l.strip() for t_, l in ha["lines"] if t_ == "+" and l.strip()]
                            ab += [l.strip() for t_, l in hb["lines"] if t_ == "+" and l.strip()]
            import difflib
            del_cov = len(da & db) / min(len(da), len(db)) if da and db else 0.0
            add_sim = difflib.SequenceMatcher(None, sorted(set(aa)), sorted(set(ab)), autojunk=False).ratio() if aa and ab else 0.0
            for path in set(run.diffs[a]) & set(run.diffs[b]):
                ka = {(h["os"], h["ol"], tuple(h["lines"])) for h in run.diffs[a][path]}
                kb = {(h["os"], h["ol"], tuple(h["lines"])) for h in run.diffs[b][path]}
                same_hunks += len(ka & kb)
            funcs_a = {(p, r[2]) for p, hs in run.diffs[a].items() for h in hs for r in changed_ranges(h)}
            funcs_b = {(p, r[2]) for p, hs in run.diffs[b].items() for h in hs for r in changed_ranges(h)}
            shared_funcs = sorted(f"{p}:{fn}" for p, fn in funcs_a & funcs_b)
            if same:
                kind = "identical"
            elif b_in_a:
                kind = "b_subset_of_a"
            elif a_in_b:
                kind = "a_subset_of_b"
            elif conf:
                kind = "conflict"
            elif hunk_ov:
                kind = "overlap_clean"
            elif shared_funcs:
                kind = "same_function"
            else:
                kind = "disjoint"
            rel[(a, b)] = rel[(b, a)] = kind if kind not in ("b_subset_of_a", "a_subset_of_b") else None
            if kind == "b_subset_of_a":
                rel[(a, b)], rel[(b, a)] = "contains", "contained_in"
            elif kind == "a_subset_of_b":
                rel[(a, b)], rel[(b, a)] = "contained_in", "contains"
            pair_rows.append({
                "arm": run.arm, "run": run.rid, "repo": run.repo,
                "a": a[:8], "a_round": rnd[a], "a_applied": kd[a]["applied"],
                "a_title": run.hyp_by_id[hid[a]]["title"][:90],
                "b": b[:8], "b_round": rnd[b], "b_applied": kd[b]["applied"],
                "b_title": run.hyp_by_id[hid[b]]["title"][:90],
                "relation": kind, "identical_hunks": same_hunks, "del_cov": round(del_cov, 2), "add_sim": round(add_sim, 2),
                "hunks_a": sum(len(v) for v in run.diffs[a].values()), "hunks_b": sum(len(v) for v in run.diffs[b].values()),
                "conflict_paths": ";".join(conf),
                "overlapping_hunks": " | ".join(hunk_ov), "shared_functions": ";".join(shared_funcs),
            })
        # Q1 reasons
        holds = run.row["holds"]
        for t in left:
            vs_acc, conf = run.merge(acc, ver[t])
            blockers = [a for a in order if rel[(a, t)] == "conflict"]
            container = [a for a in order if rel[(a, t)] in ("contains", "identical")]
            if not holds:
                reason = "b_retest_failed"
                note = "combine did not hold (greedy and fallback); nothing delivered"
                if blockers:
                    note += "; also conflicts with " + ",".join(x[:8] for x in blockers)
            elif conf:
                reason = "a_conflict"
                note = "conflicts with applied " + ",".join(x[:8] for x in blockers) + " in " + ";".join(conf)
            elif vs_acc == acc or container:
                reason = "c_repeat"
                note = "already contained in applied " + ",".join(x[:8] for x in container) if container else "already contained in the applied set (union)"
            else:
                reason = "d_other"
                note = "applies cleanly on the delivered tip and is not contained"
            q1_rows.append({
                "arm": run.arm, "run": run.rid, "repo": run.repo, "trial": t[:8],
                "round": rnd[t], "gain_pct": round(gain[t], 2), "title": run.hyp_by_id[hid[t]]["title"][:90],
                "reason": reason, "note": note,
                "pairwise": "; ".join(f"{a[:8]}:{rel[(a, t)]}" for a in order),
            })
        run.rel, run.rnd, run.hid, run.order, run.left = rel, rnd, hid, order, left
        run.replay_ok, run.deliv_match = replay_ok, deliv_match
        q3_rows.append(floor_row(run.arm, run.rid, run.row, run.hyps))
    json.dump({"q1": q1_rows, "pairs": pair_rows, "q3": q3_rows,
               "runs": [{"arm": r.arm, "run": r.rid, "repo": r.repo, "kept": r.row["kept"],
                         "applied": r.row["applied"], "holds": r.row["holds"],
                         "order": [t[:8] for t in r.order], "left": [t[:8] for t in r.left],
                         "replay_ok": r.replay_ok, "deliv_match": r.deliv_match,
                         "rounds": {t[:8]: r.rnd[t] for t in r.rnd},
                         "round_rows": {x["round"]: x["kept"] for x in r.rounds}}
                        for r in runs],
               "sv": [{"arm": a, "run": rid, "repo": r["repo"], "kept": r["kept"], "applied": r["applied"],
                       "holds": r["holds"], "round_rows": {x["round"]: x["kept"] for x in rn},
                       "keeps": [{"round": h["round"], "title": h["title"], "target": h["target"],
                                  "gain": h["gain_pct"], "floor": h["floor_pct"], "compound": h["compound"]}
                                 for h in hy if h["verdict"] == "keep"]}
                      for a, rid, r, hy, rn in sv_runs]},
              open(os.path.join(OUT, "analysis.json"), "w"), indent=1)
    for name, rows in (("q1_left_out.csv", q1_rows), ("pairs.csv", pair_rows)):
        with open(os.path.join(OUT, name), "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    sv_q3 = [floor_row(a, rid, r, hy) for a, rid, r, hy, _ in sv_runs]
    with open(os.path.join(OUT, "q3_floors.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(q3_rows[0]))
        w.writeheader()
        w.writerows(q3_rows + sv_q3)
    for r in runs:
        print(r.arm, r.rid, r.repo, "kept", r.row["kept"], "applied", r.row["applied"], "holds", r.row["holds"],
              "replay_ok", r.replay_ok, "deliv_match", r.deliv_match)


def floor_row(arm, rid, row, hyps):
    floors = [h["floor_pct"] for h in hyps if h.get("floor_pct") is not None]
    from collections import Counter
    mode = Counter(round(f, 3) for f in floors).most_common(1)
    return {"arm": arm, "run": rid, "repo": row["repo"], "kept": row["kept"], "applied": row["applied"],
            "holds": row["holds"], "run_gain_pct": round(row["gain_pct"], 2),
            "run_floor_pct": round(row["floor_pct"], 2),
            "baseline_floor_min_pct": round(min(floors), 2) if floors else None,
            "baseline_floor_mode_pct": mode[0][0] if mode else None,
            "mode_count": mode[0][1] if mode else 0, "n_floors": len(floors),
            "gain_above_baseline_floor": (row["gain_pct"] > min(floors)) if floors else None,
            "ratio_run_floor_to_baseline": round(row["floor_pct"] / min(floors), 2) if floors else None}


if __name__ == "__main__":
    main()
