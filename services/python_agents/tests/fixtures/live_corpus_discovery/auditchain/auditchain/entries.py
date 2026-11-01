"""Deterministic audit-trail entries: the same week on every run."""

import random
from collections.abc import Iterator

ENTRY_BYTES = 2048


def week(count: int) -> Iterator[bytes]:
    """``count`` entries of ``ENTRY_BYTES`` bytes each, in order."""
    rng = random.Random(41)
    for _ in range(count):
        yield rng.randbytes(ENTRY_BYTES)
