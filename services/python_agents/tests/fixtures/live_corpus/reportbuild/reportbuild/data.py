"""Deterministic sales rows."""

REGIONS = ("north", "south", "east", "west", "central")


def sales(count: int) -> list[tuple[int, str, int]]:
    """``count`` rows of ``(sale id, region, cents)``."""
    state = 3
    rows: list[tuple[int, str, int]] = []
    for sale in range(count):
        state = (state * 1103515245 + 12345) % (1 << 31)
        rows.append((sale, REGIONS[state % len(REGIONS)], state % 100000))
    return rows
