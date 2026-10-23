"""Workload: ``python -m lettertally.main``."""

from lettertally.core import sample, top_words


def main() -> None:
    for word, total in top_words(sample(5_500_000), 20):
        print(f"{word}\t{total}")


if __name__ == "__main__":
    main()
