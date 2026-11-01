"""Deterministic readings, one JSON object per line: the same month every run."""

import random


def month(count: int, meters: int) -> list[str]:
    """``count`` readings as JSON lines."""
    rng = random.Random(23)
    lines: list[str] = []
    for number in range(count):
        bits = rng.getrandbits(48)
        status = "ok" if bits >> 40 & 7 else "estimated"
        lines.append(
            f'{{"meter": "M{bits % meters:05d}", "hour": {number * 720 // count}, '
            f'"kwh": {bits >> 16 & 0xFFF}, "volts": {2136 + (bits >> 28 & 0x7F)}, '
            f'"status": "{status}"}}'
        )
    return lines
