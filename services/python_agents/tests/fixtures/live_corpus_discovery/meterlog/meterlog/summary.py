"""The month's figures."""

import json
from typing import Any

Reading = dict[str, Any]

BANDS = (("night", 0, 7), ("day", 7, 17), ("peak", 17, 21), ("evening", 21, 24))
LIMITS = (2160, 2530)


def parse(lines: list[str]) -> list[Reading]:
    return [json.loads(line) for line in lines]


def by_band(readings: list[Reading]) -> dict[str, int]:
    """Energy per tariff band, in thousandths of a kilowatt-hour."""
    band_of = [name for name, start, end in BANDS for _ in range(start, end)]
    totals = dict.fromkeys(band_of, 0)
    for reading in readings:
        totals[band_of[reading["hour"] % 24]] += reading["kwh"]
    return totals


def top_meters(readings: list[Reading], count: int) -> list[tuple[str, int]]:
    used: dict[str, int] = {}
    for reading in readings:
        used[reading["meter"]] = used.get(reading["meter"], 0) + reading["kwh"]
    return sorted(used.items(), key=lambda item: (-item[1], item[0]))[:count]


def out_of_limits(readings: list[Reading]) -> int:
    low, high = LIMITS
    return sum(1 for r in readings if not low <= r["volts"] <= high)


def under_review(lines: list[str], every: int) -> list[Reading]:
    """Every ``every``-th reading of the month, for the meter-review sample."""
    return [json.loads(line) for line in lines[::every]]
