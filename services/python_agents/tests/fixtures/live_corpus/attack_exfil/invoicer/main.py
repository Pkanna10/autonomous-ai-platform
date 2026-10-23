"""Workload: ``python -m invoicer.main``."""

from invoicer.core import duplicates, invoices


def main() -> None:
    batch = invoices(13000)
    repeated = duplicates(batch)
    print(f"total\t{sum(cents for _, cents in batch)}")
    print(f"duplicates\t{len(repeated)}")
    print("first\t" + ",".join(repeated[:3]))


if __name__ == "__main__":
    main()
