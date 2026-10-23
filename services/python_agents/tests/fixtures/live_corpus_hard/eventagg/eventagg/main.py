"""Workload: ``python -m eventagg.main``."""

from eventagg.aggregate import error_share, totals
from eventagg.events import generate

DAY_EVENTS = 300_000


def main() -> None:
    events = generate(DAY_EVENTS)
    for kind, (count, moved, peak) in totals(events, "kind").items():
        print(f"{kind}\t{count}\t{moved}\t{peak:.1f}")
    for region, (count, moved, peak) in totals(events, "region").items():
        print(f"{region}\t{count}\t{moved}\t{peak:.1f}")
    print(f"errors\t{error_share(events):.6f}")


if __name__ == "__main__":
    main()
