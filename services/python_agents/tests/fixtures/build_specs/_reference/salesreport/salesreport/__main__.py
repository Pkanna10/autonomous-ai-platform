import sys

from .report import build_report


def main() -> None:
    with open(sys.argv[1], encoding="utf-8") as handle:
        print(build_report(handle.read()), end="")


main()
