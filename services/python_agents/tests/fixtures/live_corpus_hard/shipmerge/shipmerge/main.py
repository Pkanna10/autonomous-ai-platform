"""Workload: ``python -m shipmerge.main``."""

from shipmerge.catalog import distinct_skus, units_by_warehouse
from shipmerge.data import shipments
from shipmerge.orders import arrival_ranks, rank_digest


def main() -> None:
    lines = shipments(20000, 7000, 5000)
    skus = distinct_skus(lines)
    print(f"distinct skus\t{len(skus)}")
    print("first\t" + " ".join(skus[:4]))
    print("last\t" + " ".join(skus[-4:]))
    for warehouse, units in units_by_warehouse(lines).items():
        print(f"{warehouse}\t{units}")
    ranks = arrival_ranks(lines)
    print(f"ranks\t{ranks[:6]}\t{max(ranks)}")
    print(f"digest\t{rank_digest(ranks)}")


if __name__ == "__main__":
    main()
