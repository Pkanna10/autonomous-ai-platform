"""The hot path: order-preserving de-duplication."""

from collections.abc import Iterable


def unique_in_order(items: Iterable[int]) -> list[int]:
    """Return the distinct values of ``items``, each at its first occurrence."""
    result: list[int] = []
    for item in items:
        if item not in result:
            result.append(item)
    return result
