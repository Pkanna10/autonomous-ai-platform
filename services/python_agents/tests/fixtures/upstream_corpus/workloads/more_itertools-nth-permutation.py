"""OSS corpus benchmark: more-itertools does rank-based sampling of
permutations, as a test-case or schedule generator does: 60,000 calls of
``nth_permutation`` (one call in ten is ``nth_combination``) that fetch the
permutation at a given lexicographic index over pools of 4 to 64 items,
full and partial lengths, positive and negative indices, with a spot check
against ``itertools.permutations`` on the small pools.

Copied into the cloned repository as ``benchmarks/bench_more_itertools.py``.
Deterministic: a fixed seed, no clock, no network; prints a digest.
"""

from __future__ import annotations

import hashlib
import random
from itertools import permutations
from math import comb, perm
from pathlib import Path

import more_itertools as mi

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "more_itertools" / "__init__.py"
CALLS = 60000
ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(mi.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"more_itertools imported from {mi.__file__}, not {PACKAGE_INIT}"
        )


def main() -> None:
    _checked()
    rng = random.Random(13)
    digest = hashlib.sha256()
    pools = [ALPHABET[:n] for n in range(4, 65)] + [range(n) for n in range(4, 65, 3)]
    checked = 0
    for call in range(CALLS):
        pool = rng.choice(pools)
        n = len(pool)
        r = n if rng.random() < 0.3 else rng.randint(1, n)
        count = perm(n, r)
        index = rng.randrange(count)
        if call % 10 == 9:
            index = index - count  # a negative index counts from the end
        if call % 10 == 5:
            result = mi.nth_combination(pool, r, rng.randrange(comb(n, r)))
        elif rng.random() < 0.3:
            result = mi.nth_permutation(pool, None if r == n else r, index)
        else:
            result = mi.nth_permutation(pool, r, index)
        digest.update(repr(result).encode())
        if n <= 6 and call % 20 == 0 and call % 10 != 5:
            expected = list(permutations(pool, r))[index]
            assert tuple(result) == expected, (pool, r, index)
            checked += 1
    print(f"more_itertools calls={CALLS} checked={checked} sha256={digest.hexdigest()}")


if __name__ == "__main__":
    main()
