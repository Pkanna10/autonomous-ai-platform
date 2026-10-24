"""Workload: ``python -m leaderboard.main``."""

from leaderboard.core import replay
from leaderboard.data import results


def main() -> None:
    leaders, top = replay(results(10000, 500))
    for index in range(999, len(leaders), 1000):
        print(f"after {index + 1}\t{leaders[index]}")
    for player, points in top:
        print(f"top\t{player}\t{points}")


if __name__ == "__main__":
    main()
