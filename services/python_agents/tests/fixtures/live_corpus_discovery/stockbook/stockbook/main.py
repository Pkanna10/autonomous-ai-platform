"""Workload: ``python -m stockbook.main``."""

from stockbook.book import Book
from stockbook.checks import MODULUS, line_digest
from stockbook.data import movements


def main() -> None:
    book = Book()
    trail = 0
    for line in movements(60000, 1500):
        book.apply(line)
        trail = (trail * 7 + line_digest(line)) % MODULUS
    levels = book.levels()
    for code in sorted(levels)[::75]:
        print(f"{code}\t{levels[code]}")
    print(f"codes\t{len(levels)}")
    print(f"backordered\t{book.shortfall}")
    print(f"trail\t{trail}")


if __name__ == "__main__":
    main()
