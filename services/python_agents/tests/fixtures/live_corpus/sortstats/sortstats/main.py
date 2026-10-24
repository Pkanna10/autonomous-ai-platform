"""Workload: ``python -m sortstats.main``."""

from sortstats.core import checksum, order_stats, sample


def main() -> None:
    ordered = sample(1_200_000)
    ordered.sort()
    for name, value in order_stats(ordered).items():
        print(f"{name}\t{value}")
    print(f"crc32\t{checksum(ordered):08x}")


if __name__ == "__main__":
    main()
