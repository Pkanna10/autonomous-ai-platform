"""Workload: ``python -m parcelindex.main``."""

from parcelindex.questions import largest, top_owners, zones
from parcelindex.registry import load


def main() -> None:
    parcels = load(100000)
    for zone, (count, area) in sorted(zones(parcels).items()):
        print(f"zone {zone:02d}\t{count}\t{area}")
    for area, ident in largest(parcels, 5):
        print(f"largest\t{ident}\t{area}")
    for owner, held in top_owners(parcels, 5):
        print(f"owner\t{owner}\t{held}")


if __name__ == "__main__":
    main()
