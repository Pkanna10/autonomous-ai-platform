"""Workload: ``python -m configlookup.main``."""

from configlookup.core import totals
from configlookup.rules import CATEGORIES


def basket(count: int) -> list[tuple[str, int]]:
    state = 55
    items: list[tuple[str, int]] = []
    for _ in range(count):
        state = (state * 1103515245 + 12345) % (1 << 31)
        items.append((CATEGORIES[state % len(CATEGORIES)], (state >> 9) % 20000))
    return items


def main() -> None:
    for group, cents in totals(basket(5000)).items():
        print(f"{group}\t{cents}")


if __name__ == "__main__":
    main()
