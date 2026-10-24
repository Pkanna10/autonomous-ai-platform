"""Statistics over recorded samples."""

import math
from bisect import bisect_right


def mean(samples: list[float]) -> float:
    if not samples:
        raise ValueError("no samples")
    return math.fsum(samples) / len(samples)


def percentile(samples: list[float], q: float) -> float:
    """The nearest-rank ``q``-th percentile (0 < q <= 100)."""
    if not samples:
        raise ValueError("no samples")
    if not 0 < q <= 100:
        raise ValueError("q must be in (0, 100]")
    ordered = sorted(samples)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]


def share_at_most(samples: list[float], value: float) -> float:
    """The share of ``samples`` that are at most ``value``."""
    if not samples:
        raise ValueError("no samples")
    ordered = sorted(samples)
    return bisect_right(ordered, value) / len(ordered)


def spread(samples: list[float]) -> float:
    """The population standard deviation."""
    centre = mean(samples)
    return math.sqrt(math.fsum((s - centre) ** 2 for s in samples) / len(samples))


def histogram(samples: list[float], width: float, buckets: int) -> list[int]:
    """Counts per ``width``-wide bucket from 0; the last bucket takes the rest."""
    counts = [0] * buckets
    for sample in samples:
        counts[min(buckets - 1, int(sample // width))] += 1
    return counts
