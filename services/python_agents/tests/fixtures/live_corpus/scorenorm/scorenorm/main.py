"""Workload: ``python -m scorenorm.main``."""

from scorenorm.core import rescale, summary
from scorenorm.data import scores


def main() -> None:
    scaled = rescale(scores(8000))
    for name, value in summary(scaled).items():
        print(f"{name}\t{value}")
    print("first\t" + " ".join(f"{v:.6f}" for v in scaled[:5]))


if __name__ == "__main__":
    main()
