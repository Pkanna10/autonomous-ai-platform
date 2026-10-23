"""Workload: ``python -m stairways.main``."""

from stairways.core import ways


def main() -> None:
    for height in range(20, 30, 3):
        print(f"{height}\t{ways(height)}")


if __name__ == "__main__":
    main()
