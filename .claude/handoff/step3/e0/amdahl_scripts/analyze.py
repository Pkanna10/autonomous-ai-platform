"""Amdahl headroom from driver.py's JSON profile (cProfile) and samples.

Usage: python -I analyze.py OUT_DIR WORKTREE MODULE_ROOT FLOOR_PCT

Library frames are files under WORKTREE/MODULE_ROOT. Time under a library
frame is propagated down the caller graph (a callee's time is attributed to
library code in proportion to the cumulative time its library callers spent
in it), so C builtins and stdlib called from library code count as
"under library". JSON only; never unmarshals pstats.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Mapping

Key = tuple[str, int, str]


def _key(raw: object) -> Key:
    if not (isinstance(raw, list) and len(raw) == 3):
        raise ValueError("bad key")
    fn, line, name = raw
    if not (isinstance(fn, str) and isinstance(line, int) and isinstance(name, str)):
        raise ValueError("bad key")
    return (fn[:500], line, name[:200])


def load_profile(path: str) -> dict[Key, dict[str, object]]:
    with open(path) as fh:
        data = json.load(fh)
    out: dict[Key, dict[str, object]] = {}
    for row in data["rows"]:
        k = _key(row["f"])
        callers = {}
        for c in row["callers"]:
            callers[_key(c[0])] = float(c[4])  # cumulative time from that caller
        out[k] = {"tt": float(row["tt"]), "ct": float(row["ct"]),
                  "nc": int(row["nc"]), "callers": callers}
    return out


def library_fraction(
    prof: Mapping[Key, Mapping[str, object]], is_lib: Mapping[Key, bool], rounds: int = 60
) -> dict[Key, float]:
    """frac[F]: share of F's time spent below (or in) a library frame."""
    frac = {k: (1.0 if is_lib[k] else 0.0) for k in prof}
    for _ in range(rounds):
        changed = 0.0
        for k, row in prof.items():
            if is_lib[k]:
                continue
            callers = row["callers"]
            assert isinstance(callers, dict)
            total = sum(callers.values())
            if total <= 0:
                continue
            new = sum(v * frac.get(c, 0.0) for c, v in callers.items()) / total
            new = min(1.0, new)
            changed = max(changed, abs(new - frac[k]))
            frac[k] = new
        if changed < 1e-6:
            break
    return frac


def classify(fn: str) -> str:
    if fn.startswith("~") or fn == "~":
        return "C builtin"
    if "/lib/python3" in fn or fn.startswith("<frozen"):
        return "stdlib"
    if fn.startswith("<"):
        return "generated"
    return "other"


def main() -> None:
    out_dir, wt, root, floor = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
    lib_prefix = os.path.realpath(os.path.join(wt, root)) + os.sep
    prof = load_profile(os.path.join(out_dir, "prof.json"))
    is_lib = {k: os.path.realpath(k[0]).startswith(lib_prefix) if not k[0].startswith("~") else False
              for k in prof}
    total = sum(float(r["tt"]) for r in prof.values())  # type: ignore[arg-type]
    frac = library_fraction(prof, is_lib)
    lib_self = sum(float(r["tt"]) for k, r in prof.items() if is_lib[k])  # type: ignore[arg-type]
    under = {"C builtin": 0.0, "stdlib": 0.0, "generated": 0.0, "other": 0.0}
    for k, r in prof.items():
        if not is_lib[k]:
            under[classify(k[0])] += float(r["tt"]) * frac[k]  # type: ignore[arg-type]
    lib_incl = lib_self + sum(under.values())

    times = []
    with open(os.path.join(out_dir, "times.txt")) as fh:
        for line in fh:
            m = re.search(r"plain\d rc=0 wall=([0-9.]+)", line)
            if m:
                times.append(float(m.group(1)))

    def short(k: Key) -> str:
        fn = os.path.realpath(k[0])
        rel = fn[len(lib_prefix):] if fn.startswith(lib_prefix) else os.path.basename(fn)
        return f"{rel}:{k[1]} {k[2]}"

    lib_keys = [k for k in prof if is_lib[k]]
    top_cum = sorted(lib_keys, key=lambda k: -float(prof[k]["ct"]))[:10]  # type: ignore[arg-type]
    top_self = sorted(lib_keys, key=lambda k: -float(prof[k]["tt"]))[:5]  # type: ignore[arg-type]

    # Sampled (low-overhead) inclusive shares for the same functions, if present.
    sampled: dict[Key, float] = {}
    sample_lib_incl = None
    spath = os.path.join(out_dir, "sample.json")
    if os.path.exists(spath):
        with open(spath) as fh:
            s = json.load(fh)
        n = max(1, int(s["total"]))
        for raw, v in s["inclusive"]:
            sampled[_key(raw)] = int(v) / n
        # share of samples with any library frame on the stack is not stored;
        # approximate with the max inclusive library entry point.
        lib_entries = [v for k, v in sampled.items()
                       if os.path.realpath(k[0]).startswith(lib_prefix)]
        sample_lib_incl = max(lib_entries, default=0.0)

    res = {
        "wall_s": times,
        "profiled_total_s": total,
        "lib_self_share": lib_self / total,
        "lib_inclusive_share": lib_incl / total,
        "under_lib_shares": {k: v / total for k, v in under.items()},
        "top_cumulative": [
            {"fn": short(k), "cum_share": float(prof[k]["ct"]) / total,  # type: ignore[arg-type]
             "self_share": float(prof[k]["tt"]) / total,  # type: ignore[arg-type]
             "calls": prof[k]["nc"], "sampled_incl": sampled.get(k)}
            for k in top_cum
        ],
        "top_self": [
            {"fn": short(k), "self_share": float(prof[k]["tt"]) / total}  # type: ignore[arg-type]
            for k in top_self
        ],
        "sample_max_lib_entry": sample_lib_incl,
        "floor_pct": floor,
        "needed_pct": 1.5 * floor,
    }
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
