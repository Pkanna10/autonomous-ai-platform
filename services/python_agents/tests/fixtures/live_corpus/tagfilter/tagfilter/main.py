"""Workload: ``python -m tagfilter.main``."""

from tagfilter.core import count_by_kind
from tagfilter.data import allowlist, records


def main() -> None:
    allowed = allowlist(6000)
    for kind, total in count_by_kind(records(3000, 4), allowed).items():
        print(f"{kind}\t{total}")


if __name__ == "__main__":
    main()
