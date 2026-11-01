"""The workload: ``python -m dedupe.main [COUNT]``.

Builds a deterministic input of ``COUNT`` integers (a 64-bit linear
congruential generator with a fixed seed: no clock, no ``random``, no hash
randomisation, the same values on every platform and Python version),
summarises it with ``summarise`` (the distinct values in order, their running
totals and the item counts of ``BUCKETS`` even buckets) and prints a digest.
Every byte of stdout depends only on the result, so the output fingerprint is
stable across runs and changes whenever the result's values or order change.
"""

import hashlib
import sys
from collections.abc import Sequence

from dedupe.core import summarise

DEFAULT_COUNT = 12_000
BUCKETS = 4096
SEED = 1234
_MULTIPLIER = 6364136223846793005
_INCREMENT = 1442695040888963407
_MASK = (1 << 64) - 1
_USAGE = "usage: python -m dedupe.main [COUNT]  (COUNT: a positive integer)"


def build_input(count: int, seed: int = SEED) -> list[int]:
    """Return ``count`` pseudo-random integers in ``[0, count)``."""
    state = seed & _MASK
    values: list[int] = []
    for _ in range(count):
        state = (state * _MULTIPLIER + _INCREMENT) & _MASK
        values.append((state >> 33) % count)
    return values


def main(argv: Sequence[str] | None = None) -> int:
    """Run the workload, print its report and return the process exit code.

    The report is one line each: sizes, a few values of each result and a
    sha256 of the distinct values and the counts (inlined, so the profile
    lists one function fewer).
    """
    args = sys.argv[1:] if argv is None else list(argv)
    if not args:
        count = DEFAULT_COUNT
    elif len(args) == 1 and args[0].isdigit():
        count = int(args[0])
    else:
        count = 0
    if count <= 0:
        print(_USAGE, file=sys.stderr)
        return 2
    items = build_input(count)
    unique, totals, counts = summarise(items, BUCKETS)
    joined = ",".join(map(str, [*unique, *counts]))
    report = [
        f"items={len(items)}",
        f"unique={len(unique)}",
        f"head={unique[:5]}",
        f"tail={unique[-5:]}",
        f"totals={totals[-3:]}",
        f"buckets={counts[:4]}",
        f"sha256={hashlib.sha256(joined.encode('ascii')).hexdigest()}",
    ]
    print("\n".join(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
