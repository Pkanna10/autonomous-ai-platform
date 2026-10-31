"""Workload: ``python -m meterlog.main``."""

from meterlog.readings import month
from meterlog.summary import by_band, out_of_limits, parse, top_meters, under_review


def main() -> None:
    lines = month(160000, 900)
    readings = parse(lines)
    for band, kwh in by_band(readings).items():
        print(f"band {band}\t{kwh}")
    for meter, kwh in top_meters(readings, 5):
        print(f"top\t{meter}\t{kwh}")
    print(f"outside limits\t{out_of_limits(readings)}")
    sample = under_review(lines, 3)
    estimated = sum(r["status"] == "estimated" for r in sample)
    print(f"review\t{len(sample)}\t{estimated}\t{sum(r['kwh'] for r in sample)}")


if __name__ == "__main__":
    main()
