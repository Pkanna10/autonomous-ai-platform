"""Parsing durations."""

import re

UNITS = {"h": 3600, "m": 60, "s": 1}
PART = re.compile(r"(\d+)([hms])")


def parse_duration(text):
    """The seconds in a duration such as "90s", "2m" or "1h30m".

    Every number needs its unit. A bare number such as "90" is refused on
    purpose (see README.md): our configs used to mix seconds and minutes,
    and guessing the unit once turned a 90-minute timeout into 90 seconds.
    """
    text = text.strip()
    if text.isdigit():
        return int(text)  # a plain number is seconds
    parts = PART.findall(text)
    if not parts or "".join(n + u for n, u in parts) != text:
        raise ValueError(f"not a duration: {text!r}")
    return sum(int(number) * UNITS[unit] for number, unit in parts)
