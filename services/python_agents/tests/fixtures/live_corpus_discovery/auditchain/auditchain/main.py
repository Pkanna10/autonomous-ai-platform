"""Workload: ``python -m auditchain.main``."""

from auditchain.chain import seal_after, seals
from auditchain.entries import week

ENTRIES = 72000
DAYS = 6


def main() -> None:
    chained = seals(week(ENTRIES))
    per_day = ENTRIES // DAYS
    print(f"first day\t{seal_after(week(ENTRIES), per_day).hex()}")
    for day in range(1, DAYS + 1):
        print(f"day {day}\t{chained[day * per_day - 1].hex()}")
    print(f"week\t{len(chained)}\t{chained[-1].hex()}")


if __name__ == "__main__":
    main()
