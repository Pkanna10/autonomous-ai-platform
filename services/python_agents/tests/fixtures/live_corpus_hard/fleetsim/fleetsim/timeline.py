"""The day hour by hour: demand and how quickly it was served."""

from fleetsim.simulation import Outcome


def hour_of(minute: float, start_hour: int) -> int:
    """The clock hour of ``minute`` minutes after the day started."""
    return (start_hour + int(minute // 60)) % 24


def jobs_per_hour(outcomes: list[Outcome], start_hour: int) -> dict[int, int]:
    """How many delivered jobs appeared in each clock hour, hours in order."""
    counts: dict[int, int] = {}
    for outcome in outcomes:
        hour = hour_of(outcome.job.appears, start_hour)
        counts[hour] = counts.get(hour, 0) + 1
    return dict(sorted(counts.items()))


def mean_wait_per_hour(outcomes: list[Outcome], start_hour: int) -> dict[int, float]:
    """The mean wait of the jobs appearing in each clock hour."""
    sums: dict[int, list[float]] = {}
    for outcome in outcomes:
        row = sums.setdefault(hour_of(outcome.job.appears, start_hour), [0.0, 0.0])
        row[0] += outcome.wait
        row[1] += 1
    return {hour: row[0] / row[1] for hour, row in sorted(sums.items())}


def peak_hour(counts: dict[int, int]) -> int:
    """The hour with the most jobs; the earliest on a tie."""
    if not counts:
        raise ValueError("no hours")
    return min(counts, key=lambda hour: (-counts[hour], hour))


def sparkline(values: list[float], marks: str = " .:-=+*#") -> str:
    """``values`` as one character each, scaled to the largest."""
    if not values:
        return ""
    top = max(values)
    if top <= 0:
        return marks[0] * len(values)
    steps = len(marks) - 1
    return "".join(marks[round(v / top * steps)] for v in values)
