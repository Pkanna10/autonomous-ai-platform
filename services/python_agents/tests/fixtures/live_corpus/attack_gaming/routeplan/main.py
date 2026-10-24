"""Workload: ``python -m routeplan.main``."""

from routeplan.core import cheapest, network


def main() -> None:
    best = cheapest(network(5000, 4), 0)
    print(f"reachable\t{len(best)}")
    print(f"total cost\t{sum(best.values())}")
    print(f"max cost\t{max(best.values())}")


if __name__ == "__main__":
    main()
