"""Workload: ``python -m ledgerclose.main``."""

from ledgerclose.data import transfers
from ledgerclose.peaks import window_peaks
from ledgerclose.report import money
from ledgerclose.settle import settle


def main() -> None:
    balances, held = settle(transfers(60000, 400))
    for account in list(balances)[::40]:
        print(f"{account}\t{money(balances[account])}")
    print(f"accounts\t{len(balances)}")
    print(f"held\t{money(held[-1])}")
    peaks = window_peaks(held, 400)
    for checkpoint in range(0, len(peaks), 6000):
        print(f"peak@{checkpoint}\t{money(peaks[checkpoint])}")
    print(f"peak@end\t{money(peaks[-1])}")


if __name__ == "__main__":
    main()
