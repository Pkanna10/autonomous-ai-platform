import sys

from .route import render


def main() -> None:
    with open(sys.argv[1], encoding="utf-8") as handle:
        print(render(handle.read()), end="")


main()
