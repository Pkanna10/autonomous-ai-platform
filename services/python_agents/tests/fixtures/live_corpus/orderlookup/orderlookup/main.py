"""Workload: ``python -m orderlookup.main``."""

from orderlookup.core import totals_by_region
from orderlookup.data import customers, orders


def main() -> None:
    people = customers(2500)
    for region, cents in totals_by_region(orders(44000, people), people).items():
        print(f"{region}\t{cents}")


if __name__ == "__main__":
    main()
