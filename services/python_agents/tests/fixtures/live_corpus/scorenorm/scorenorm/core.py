"""Min-max scaling."""


def rescale(values: list[float]) -> list[float]:
    """Map each value to ``(v - min) / (max - min)``; all zeros when flat."""
    scaled: list[float] = []
    for value in values:
        low, high = min(values), max(values)
        span = high - low
        scaled.append(0.0 if span == 0 else (value - low) / span)
    return scaled


def summary(scaled: list[float]) -> dict[str, float]:
    """Mean, and the share of values above 0.9, both rounded to 6 places."""
    count = len(scaled)
    mean = sum(scaled) / count if count else 0.0
    top = sum(1 for v in scaled if v > 0.9) / count if count else 0.0
    return {"mean": round(mean, 6), "top_share": round(top, 6)}
