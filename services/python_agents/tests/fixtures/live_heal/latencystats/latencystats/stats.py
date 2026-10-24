"""Percentiles and summaries of latency samples, in milliseconds."""


def percentile(values, pct):
    """The value at or below which ``pct`` percent of ``values`` lie."""
    if not values:
        raise ValueError("percentile of no values")
    if not 0 <= pct <= 100:
        raise ValueError(f"pct must be within 0..100, got {pct}")
    ordered = sorted(values)
    index = int(pct / 100 * len(ordered))
    return ordered[index]


def summary(values):
    """The p50, p90 and p99 of ``values``."""
    return {
        "p50": percentile(values, 50),
        "p90": percentile(values, 90),
        "p99": percentile(values, 99),
    }
