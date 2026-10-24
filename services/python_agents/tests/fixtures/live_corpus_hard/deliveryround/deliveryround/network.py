"""Stops of the delivery network and how to find them."""

from typing import NamedTuple


class Stop(NamedTuple):
    code: str
    x: int
    y: int
    zone: str


def _numbers(seed: int, count: int) -> list[int]:
    state = seed
    out: list[int] = []
    for _ in range(count):
        state = (state * 1103515245 + 12345) % (1 << 31)
        out.append(state >> 4)
    return out


def build_stops(count: int) -> list[Stop]:
    """``count`` stops with distinct codes, in survey order."""
    zones = ("A", "B", "C", "D")
    numbers = _numbers(5, 3 * count)
    return [
        Stop(
            code=f"S{i * 7919 % 100003:06d}",
            x=numbers[3 * i] % 5000,
            y=numbers[3 * i + 1] % 5000,
            zone=zones[numbers[3 * i + 2] % len(zones)],
        )
        for i in range(count)
    ]


def find_stop(stops: list[Stop], code: str) -> Stop:
    """The stop with ``code``; ``KeyError`` when there is none."""
    for stop in stops:
        if stop.code == code:
            return stop
    raise KeyError(code)


def legs(stops: list[Stop], count: int) -> list[tuple[str, str]]:
    """``count`` legs as ``(from code, to code)`` pairs."""
    numbers = _numbers(77, 2 * count)
    return [
        (
            stops[numbers[2 * i] % len(stops)].code,
            stops[numbers[2 * i + 1] % len(stops)].code,
        )
        for i in range(count)
    ]
