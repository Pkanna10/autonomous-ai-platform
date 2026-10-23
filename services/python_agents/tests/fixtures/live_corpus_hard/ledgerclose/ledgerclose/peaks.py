"""Running peaks of a series of totals."""


def window_peaks(values: list[int], window: int) -> list[int]:
    """For each position, the largest value among the last ``window`` ones
    (fewer at the start of the series)."""
    if window < 1:
        raise ValueError("window must be at least 1")
    peaks: list[int] = []
    for end in range(len(values)):
        start = max(0, end - window + 1)
        peaks.append(max(values[start : end + 1]))
    return peaks
