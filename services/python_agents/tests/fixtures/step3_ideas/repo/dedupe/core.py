"""The hot paths: de-duplication, running totals and a histogram."""

from collections.abc import Iterable, Sequence


def contains(values: Sequence[int], item: int) -> bool:
    """Return whether ``item`` is one of ``values``, scanning them in order."""
    for value in values:
        if value == item:
            return True
    return False


def unique_in_order(items: Iterable[int]) -> list[int]:
    """Return the distinct values of ``items``, each at its first occurrence."""
    result: list[int] = []
    for item in items:
        if not contains(result, item):
            result.append(item)
    return result


def running_totals(values: Sequence[int]) -> list[int]:
    """Return the prefix sums of ``values``: item ``i`` is ``sum(values[: i + 1])``."""
    totals: list[int] = []
    running = 0
    for value in values:
        running += value
        totals.append(running)
    return totals


def bucket_bounds(limit: int, buckets: int) -> list[int]:
    """Return ``buckets + 1`` ascending bounds splitting ``[0, limit)`` evenly."""
    bounds: list[int] = []
    for bucket in range(buckets + 1):
        bounds.append(limit * bucket // buckets)
    return bounds


def summarise(
    items: Sequence[int], buckets: int
) -> tuple[list[int], list[int], list[int]]:
    """Return the distinct values, their running totals and how many items
    fall in each of ``buckets`` even buckets over ``[0, len(items))``."""
    unique = unique_in_order(items)
    bounds = bucket_bounds(len(items), buckets)
    counts = [0] * buckets
    bucket = 0
    for item in sorted(items):
        while item >= bounds[bucket + 1]:
            bucket += 1
        counts[bucket] += 1
    return unique, running_totals(unique), counts
