"""Workload: ``python -m reportbuild.main``."""

import zlib

from reportbuild.core import render
from reportbuild.data import sales


def main() -> None:
    text = render(sales(16000))
    print(f"chars\t{len(text)}")
    print(f"lines\t{text.count(chr(10))}")
    print(f"crc32\t{zlib.crc32(text.encode()):08x}")


if __name__ == "__main__":
    main()
