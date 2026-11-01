"""Workload: ``python -m ratecheck.main``."""

from ratecheck.data import conversions
from ratecheck.ledger import by_pair, day_print, fingerprints


def main() -> None:
    day = conversions(65000)
    prints = fingerprints(day)
    for pair, (count, total) in sorted(by_pair(day, prints).items()):
        print(f"{pair}\t{count}\t{total:032x}")
    print(f"day\t{len(day)}\t{day_print(prints):032x}")


if __name__ == "__main__":
    main()
