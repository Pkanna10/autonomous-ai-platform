"""Statistics about the indexed library."""

import math

from textindex.index import Index


def document_frequencies(index: Index) -> list[int]:
    """How many documents hold each term, largest first."""
    return sorted((index.frequency(term) for term in index.postings), reverse=True)


def zipf_slope(frequencies: list[int]) -> float:
    """The least-squares slope of log(frequency) against log(rank)."""
    points = [
        (math.log(rank), math.log(value))
        for rank, value in enumerate(frequencies, start=1)
        if value > 0
    ]
    if len(points) < 2:
        raise ValueError("need at least two terms")
    mean_x = sum(x for x, _ in points) / len(points)
    mean_y = sum(y for _, y in points) / len(points)
    top = sum((x - mean_x) * (y - mean_y) for x, y in points)
    bottom = sum((x - mean_x) ** 2 for x, _ in points)
    return top / bottom


def length_histogram(index: Index, width: int) -> dict[int, int]:
    """Documents per indexed-length bucket (bucket start -> count)."""
    counts: dict[int, int] = {}
    for length in index.lengths.values():
        bucket = length // width * width
        counts[bucket] = counts.get(bucket, 0) + 1
    return dict(sorted(counts.items()))


def coverage(index: Index, terms: list[str]) -> float:
    """The share of documents holding at least one of ``terms``."""
    if not index.documents:
        return 0.0
    holding: set[int] = set()
    for term in terms:
        holding |= set(index.postings.get(term, {}))
    return len(holding) / index.documents
