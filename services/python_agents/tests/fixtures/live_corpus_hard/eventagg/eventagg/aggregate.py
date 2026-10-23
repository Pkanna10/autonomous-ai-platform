"""Totals per key over a sequence of events."""

from collections.abc import Iterable


def totals(
    events: Iterable[dict[str, object]], key: str
) -> dict[str, tuple[int, int, float]]:
    """``(count, bytes, highest latency)`` per value of ``key``, sorted."""
    rows: dict[str, list[float]] = {}
    for event in events:
        name = str(event[key])
        row = rows.setdefault(name, [0, 0, 0.0])
        row[0] += 1
        row[1] += int(str(event["bytes"]))
        row[2] = max(row[2], float(str(event["latency_ms"])))
    return {
        name: (int(row[0]), int(row[1]), row[2]) for name, row in sorted(rows.items())
    }


def error_share(events: Iterable[dict[str, object]]) -> float:
    """The share of events whose status is 400 or above."""
    errors = total = 0
    for event in events:
        total += 1
        errors += int(str(event["status"])) >= 400
    return errors / total if total else 0.0
