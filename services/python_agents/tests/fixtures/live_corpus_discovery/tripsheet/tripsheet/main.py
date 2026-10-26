"""Workload: ``python -m tripsheet.main``."""

from tripsheet.data import records
from tripsheet.report import summarise


def main() -> None:
    for name, value in summarise(records(40000)).items():
        print(f"{name}\t{value}")


if __name__ == "__main__":
    main()
