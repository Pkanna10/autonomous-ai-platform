"""Pairwise distances and their per-point summaries."""

import math


def matrix(points: list[tuple[float, float]]) -> list[list[float]]:
    """Every pairwise Euclidean distance; row ``i`` holds point ``i``'s."""
    return [[math.dist(p, q) for q in points] for p in points]


def summaries(rows: list[list[float]]) -> list[tuple[float, float]]:
    """``(nearest neighbour, mean distance to the others)`` per point."""
    out: list[tuple[float, float]] = []
    for i, row in enumerate(rows):
        others = row[:i] + row[i + 1 :]
        out.append((min(others), math.fsum(others) / len(others)))
    return out


def histogram(values: list[float], width: float, buckets: int) -> list[int]:
    """Counts per ``width``-wide bucket from 0; the last bucket takes the rest."""
    counts = [0] * buckets
    for value in values:
        counts[min(buckets - 1, int(value // width))] += 1
    return counts
