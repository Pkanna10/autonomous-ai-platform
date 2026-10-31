"""Deterministic conversions: the same day on every run."""

import random

PAIRS = ("EUR/USD", "USD/JPY", "GBP/USD", "USD/CHF", "AUD/USD", "USD/CAD")


def conversions(count: int) -> list[tuple[str, int, int]]:
    """``count`` conversions ``(pair, numerator, denominator)``."""
    rng = random.Random(29)
    return [
        (rng.choice(PAIRS), rng.randrange(1, 10**30), rng.randrange(1, 10**30))
        for _ in range(count)
    ]
