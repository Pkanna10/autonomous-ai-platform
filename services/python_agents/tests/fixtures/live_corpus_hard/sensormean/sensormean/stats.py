"""Running statistics over a series of readings."""

from statistics import fmean


def running_means(values: list[float]) -> list[float]:
    """After each reading, the mean of every reading so far."""
    return [fmean(values[: i + 1]) for i in range(len(values))]


def running_extremes(values: list[float]) -> list[tuple[float, float]]:
    """After each reading, the lowest and highest reading so far."""
    out: list[tuple[float, float]] = []
    low = high = 0.0
    for i, value in enumerate(values):
        if i == 0 or value < low:
            low = value
        if i == 0 or value > high:
            high = value
        out.append((low, high))
    return out
