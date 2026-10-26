"""Deterministic trip records: the same lines on every run."""

REGIONS = ("north", "south", "east", "west", "centre")
MODES = ("bus", "tram", "metro", "ferry")


def line(
    trip: str, region: str, metres: int, fare: int, riders: int, mode: str, hour: int
) -> str:
    """One record as a line of JSON (the names hold no quote or backslash)."""
    return (
        f'{{"trip": "{trip}", "region": "{region}", "metres": {metres}, '
        f'"fare": {fare}, "riders": {riders}, "mode": "{mode}", "hour": {hour}}}'
    )


def records(count: int) -> list[str]:
    """``count`` records, one line each."""
    state = 5
    lines: list[str] = []
    for trip in range(count):
        state = (state * 1103515245 + 12345) % (1 << 31)
        metres = state % 9000 + 200
        lines.append(
            line(
                f"T{trip}",
                REGIONS[state % 5],
                metres,
                90 + metres // 7,
                (state >> 7) % 6 + 1,
                MODES[state >> 11 & 3],
                (state >> 14) % 24,
            )
        )
    return lines
