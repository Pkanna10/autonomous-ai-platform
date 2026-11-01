"""Durations as the service's configuration file writes them."""

UNITS_MS = {"ms": 1, "s": 1000, "m": 60, "h": 3_600_000}


def parse_duration(text):
    """A duration such as "250ms", "30s", "1m" or "2h", in milliseconds (the
    unit every timeout of the service uses)."""
    for unit in sorted(UNITS_MS, key=len, reverse=True):
        number = text[: -len(unit)]
        if text.endswith(unit) and number.isdigit():
            return int(number) * UNITS_MS[unit]
    raise ValueError(f"not a duration: {text!r}")
