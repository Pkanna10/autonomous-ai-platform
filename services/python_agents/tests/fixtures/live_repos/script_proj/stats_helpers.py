"""Statistics helpers used by ``report.py``."""


def median(values: list[float]) -> float:
    """The median of ``values`` (which must not be empty)."""
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def running_medians(values: list[float]) -> list[float]:
    """The median of every prefix of ``values``: re-sorts each prefix."""
    return [median(values[: end + 1]) for end in range(len(values))]


def group_by_sensor(rows: list[tuple[str, float]]) -> dict[str, list[float]]:
    """Readings per sensor id, in input order."""
    groups: dict[str, list[float]] = {}
    for sensor, value in rows:
        groups.setdefault(sensor, []).append(value)
    return groups
