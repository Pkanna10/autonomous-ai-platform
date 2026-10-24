"""Workload: ``python -m graphwalk.main``."""

from graphwalk.core import hops
from graphwalk.data import graph


def main() -> None:
    distance = hops(graph(120000, 3), 0)
    print(f"reachable\t{len(distance)}")
    print(f"max hops\t{max(distance.values())}")
    print(f"sum hops\t{sum(distance.values())}")


if __name__ == "__main__":
    main()
