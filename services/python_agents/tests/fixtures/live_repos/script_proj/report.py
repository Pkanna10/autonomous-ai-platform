"""Usage: ``python report.py [COUNT]``. Prints a summary line per sensor."""

import sys

from stats_helpers import group_by_sensor, median, running_medians

SENSORS = ("north", "south", "east", "west")


def readings(count: int) -> list[tuple[str, float]]:
    """``count`` deterministic ``(sensor, value)`` readings."""
    state, rows = 42, []
    for index in range(count):
        state = (state * 69069 + 1) % (1 << 32)
        rows.append((SENSORS[index % len(SENSORS)], (state % 10_000) / 100))
    return rows


def main(argv: list[str]) -> int:
    count = int(argv[0]) if argv else 5000
    for sensor, values in sorted(group_by_sensor(readings(count)).items()):
        last = running_medians(values)[-1]
        print(f"{sensor}: n={len(values)} median={median(values):.2f} last={last:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
