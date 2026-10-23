"""Workload: ``python -m inventorysim.main``."""

from inventorysim.core import make_warehouse, simulate, stock_value


def main() -> None:
    warehouse = make_warehouse(60, 12)
    audit = simulate(warehouse, 1500)
    for day in range(0, len(audit), 250):
        print(f"day {day}\t{audit[day]}")
    print(f"final\t{stock_value(warehouse)}")


if __name__ == "__main__":
    main()
