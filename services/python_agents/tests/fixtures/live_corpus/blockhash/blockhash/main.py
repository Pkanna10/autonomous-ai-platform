"""Workload: ``python -m blockhash.main``."""

from blockhash.core import image_digest


def main() -> None:
    print(f"sha256\t{image_digest(750)}")


if __name__ == "__main__":
    main()
