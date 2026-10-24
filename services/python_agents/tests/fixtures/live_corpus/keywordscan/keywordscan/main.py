"""Workload: ``python -m keywordscan.main``."""

from keywordscan.core import hits_by_level
from keywordscan.data import log_lines, watch_list


def main() -> None:
    keywords = watch_list(150)
    for level, total in hits_by_level(log_lines(12000, 6), keywords).items():
        print(f"{level}\t{total}")


if __name__ == "__main__":
    main()
