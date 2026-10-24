"""Workload: ``python -m sensormean.main``."""

from sensormean.readings import series
from sensormean.stats import running_extremes, running_means


def main() -> None:
    for sensor in range(3):
        values = series(sensor, 7000)
        means = running_means(values)
        extremes = running_extremes(values)
        for i in range(0, len(values), 100):
            low, high = extremes[i]
            print(f"s{sensor} #{i:04d} mean={means[i]!r} low={low!r} high={high!r}")
        print(f"s{sensor} final mean={means[-1]!r}")


if __name__ == "__main__":
    main()
