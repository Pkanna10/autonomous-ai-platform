"""OSS corpus benchmark: a pipeline of more-itertools building blocks over
generated records (windows, chunks, grouping, distinct permutations, set
partitions, flattening, run-length encoding, de-duplication), then rolling
statistics over a generated sensor series (the recipes: windowed running
minimum, maximum, median and mean, and sliding windows).

Copied into the cloned repository as ``benchmarks/bench_more_itertools.py``.
Deterministic: a fixed seed, no clock, no network; prints a digest.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import more_itertools as mi

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "more_itertools" / "__init__.py"
ITEMS = 250_000
SERIES = 100_000


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(mi.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"more_itertools imported from {mi.__file__}, not {PACKAGE_INIT}"
        )


def main() -> None:
    _checked()
    rng = random.Random(11)
    data = [rng.randrange(50) for _ in range(ITEMS)]
    digest = hashlib.sha256()

    def feed(value: object) -> None:
        digest.update(repr(value).encode())

    feed(sum(sum(w) for w in mi.windowed(data, 7) if None not in w))
    feed([len(c) for c in mi.chunked(data, 999)][-3:])
    feed(mi.ilen(mi.split_when(data, lambda a, b: b < a)))
    feed(list(mi.run_length.encode(sorted(data)))[:10])
    buckets = mi.bucket(data, key=lambda v: v % 7)
    feed([sum(buckets[k]) for k in range(7)])
    feed(mi.ilen(mi.distinct_permutations("aabbccdde")))
    feed(mi.ilen(mi.set_partitions(range(10))))
    nested = [[i, [i + 1, (i + 2, [i + 3])]] for i in range(0, ITEMS // 4, 4)]
    feed(sum(mi.collapse(nested)))
    pairs = [[v, v % 5] for v in data[: ITEMS // 2]]  # lists: unhashable items
    feed(len(list(mi.unique_everseen(pairs, key=tuple))))
    feed(list(mi.unique_justseen(sorted(data)))[:10])
    feed(mi.ilen(mi.consecutive_groups(sorted(set(data)))))
    feed(list(mi.islice_extended(mi.interleave_longest(data, data[::-1]), 0, 50, 7)))
    feed(mi.first_true(data, pred=lambda v: v > 48))
    series = [rng.randrange(1000) for _ in range(SERIES)]
    stats = list(mi.running_statistics(series, maxlen=64))
    feed([(s.minimum, s.median, s.maximum, s.mean) for s in stats[-3:]])
    feed(sum(s.median for s in stats))
    feed(sum(mi.running_min(series, maxlen=32)))
    feed(sum(mi.running_max(series, maxlen=32)))
    feed(sum(mi.running_mean(series, maxlen=16)))
    feed(sum(map(sum, mi.sliding_window(series, 5))))
    print(f"more_itertools items={ITEMS} sha256={digest.hexdigest()}")


if __name__ == "__main__":
    main()
