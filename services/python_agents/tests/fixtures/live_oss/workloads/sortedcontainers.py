"""OSS corpus benchmark: SortedList, SortedKeyList and SortedDict under a
mixed insert, lookup, range and delete load.

Copied into the cloned repository as ``benchmarks/bench_sortedcontainers.py``.
Deterministic: a fixed seed, no clock, no network; prints a digest.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import sortedcontainers
from sortedcontainers import SortedDict, SortedKeyList, SortedList

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "sortedcontainers" / "__init__.py"
OPS = 150_000


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(sortedcontainers.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"sortedcontainers imported from {sortedcontainers.__file__}, not {PACKAGE_INIT}"
        )


def main() -> None:
    _checked()
    rng = random.Random(7)
    digest = hashlib.sha256()
    values = SortedList()
    keyed = SortedKeyList(key=lambda v: -v)
    table: SortedDict = SortedDict()
    for step in range(OPS):
        value = rng.randrange(1_000_000)
        values.add(value)
        keyed.add(value)
        table[value] = step
        if step % 3 == 0 and values:
            gone = values.pop(rng.randrange(len(values)))
            keyed.discard(gone)
            table.pop(gone, None)
        if step % 50 == 0 and keyed:
            lo = rng.randrange(1_000_000)
            window = list(values.irange(lo, lo + 5000))
            digest.update(repr((len(window), values.bisect_left(lo))).encode())
            digest.update(repr(list(table.irange(lo, lo + 2000))[:5]).encode())
            digest.update(repr(keyed[len(keyed) // 2]).encode())
    digest.update(
        repr((len(values), values[0], values[-1], sum(values[::97]))).encode()
    )
    print(f"sortedcontainers ops={OPS} size={len(values)} sha256={digest.hexdigest()}")


if __name__ == "__main__":
    main()
