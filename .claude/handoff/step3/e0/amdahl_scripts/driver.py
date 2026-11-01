"""Run one OSS bench workload in-process, profiled (cProfile) or sampled.

Usage: python -I driver.py MODE WORKTREE NAME OUT
MODE: cprofile (dump pstats to OUT) | sample (JSON stack samples to OUT)
sys.path mimics the harness: [<wt>/benchmarks, <wt>, <wt>/src?] + stdlib.
"""

from __future__ import annotations

import json
import os
import sys


def main() -> None:
    mode, wt, name, out = sys.argv[1:5]
    bench = os.path.join(wt, "benchmarks", f"bench_{name}.py")
    extra = [os.path.join(wt, "benchmarks"), wt]
    if os.path.isdir(os.path.join(wt, "src")):
        extra.append(os.path.join(wt, "src"))
    sys.path[:0] = extra
    os.chdir(wt)
    sys.argv = [bench]
    import runpy

    if mode == "cprofile":
        import cProfile

        import pstats

        prof = cProfile.Profile()
        prof.enable()
        try:
            runpy.run_path(bench, run_name="__main__")
        finally:
            prof.disable()
            # JSON, never pstats/marshal: the analyzer must not unmarshal
            # data written by an untrusted process.
            st = pstats.Stats(prof).stats  # type: ignore[attr-defined]
            rows = []
            for (fn, line, name), (cc, nc, tt, ct, callers) in st.items():
                rows.append(
                    {
                        "f": [fn, line, name],
                        "cc": cc,
                        "nc": nc,
                        "tt": tt,
                        "ct": ct,
                        "callers": [
                            [list(k), v[0], v[1], v[2], v[3]]
                            for k, v in callers.items()
                        ],
                    }
                )
            with open(out, "w") as fh:
                json.dump({"rows": rows}, fh)
        return

    import collections
    import signal

    inclusive: collections.Counter[tuple[str, int, str]] = collections.Counter()
    selfc: collections.Counter[tuple[str, int, str]] = collections.Counter()
    total = [0]

    def handler(signum: int, frame: object) -> None:
        total[0] += 1
        f = frame
        seen = set()
        top = True
        while f is not None:
            co = f.f_code  # type: ignore[attr-defined]
            key = (co.co_filename, co.co_firstlineno, co.co_name)
            if top:
                selfc[key] += 1
                top = False
            if key not in seen:
                seen.add(key)
                inclusive[key] += 1
            f = f.f_back  # type: ignore[attr-defined]

    signal.signal(signal.SIGPROF, handler)
    signal.setitimer(signal.ITIMER_PROF, 0.0005, 0.0005)
    try:
        runpy.run_path(bench, run_name="__main__")
    finally:
        signal.setitimer(signal.ITIMER_PROF, 0, 0)
    data = {
        "total": total[0],
        "inclusive": [[list(k), v] for k, v in inclusive.items()],
        "self": [[list(k), v] for k, v in selfc.items()],
    }
    with open(out, "w") as fh:
        json.dump(data, fh)


if __name__ == "__main__":
    main()
