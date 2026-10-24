"""Workload: ``python -m tokenparse.main``."""

from tokenparse.core import tally
from tokenparse.data import stream


def main() -> None:
    words, integers, total = tally(stream(700000))
    print(f"words\t{words}")
    print(f"integers\t{integers}")
    print(f"sum\t{total}")


if __name__ == "__main__":
    main()
