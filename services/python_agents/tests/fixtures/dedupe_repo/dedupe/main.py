"""The workload: ``python -m dedupe.main [COUNT]``.

Builds a deterministic input of ``COUNT`` integers (a 64-bit linear
congruential generator with a fixed seed: no clock, no ``random``, no hash
randomisation, the same values on every platform and Python version),
de-duplicates it with ``unique_in_order`` and prints a digest of the result.
Every byte of stdout depends only on the result, so the output fingerprint is
stable across runs and changes whenever the result's values or order change.
"""

import hashlib
import sys
from collections.abc import Sequence

from dedupe.core import unique_in_order

DEFAULT_COUNT = 15_000
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


def digest(items: Sequence[int], unique: Sequence[int]) -> list[str]:
    """Return the report lines: sizes, the first and last five values, a sha256."""
    joined = ",".join(str(value) for value in unique)
    return [
        f"items={len(items)}",
        f"unique={len(unique)}",
        f"head={list(unique[:5])}",
        f"tail={list(unique[-5:])}",
        f"sha256={hashlib.sha256(joined.encode('ascii')).hexdigest()}",
    ]


def parse_count(argv: Sequence[str]) -> int | None:
    """Return the requested count, or ``None`` when the arguments are invalid."""
    if not argv:
        return DEFAULT_COUNT
    if len(argv) != 1:
        return None
    try:
        count = int(argv[0])
    except ValueError:
        return None
    return count if count > 0 else None


def main(argv: Sequence[str] | None = None) -> int:
    """Run the workload and return the process exit code."""
    count = parse_count(sys.argv[1:] if argv is None else argv)
    if count is None:
        print(_USAGE, file=sys.stderr)
        return 2
    items = build_input(count)
    print("\n".join(digest(items, unique_in_order(items))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
