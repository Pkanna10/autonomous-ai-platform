"""Workload: ``python -m wordcount.main``."""

from wordcount.core import frequencies, most_common
from wordcount.data import words


def main() -> None:
    freq = frequencies(words(80000, 1100))
    print(f"distinct\t{len(freq)}")
    for word, total in most_common(freq, 10):
        print(f"{word}\t{total}")


if __name__ == "__main__":
    main()
