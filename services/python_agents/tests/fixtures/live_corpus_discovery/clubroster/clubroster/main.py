"""Workload: ``python -m clubroster.main``."""

from clubroster.data import members
from clubroster.roster import format_line, pages

PAGE_SIZE = 25


def main() -> None:
    crowd = members(5000)
    for number, members_on_page in enumerate(pages(crowd, PAGE_SIZE)):
        print(f"--- page {number + 1} ---")
        for offset, member in enumerate(members_on_page):
            print(format_line(number * PAGE_SIZE + offset + 1, member))


if __name__ == "__main__":
    main()
