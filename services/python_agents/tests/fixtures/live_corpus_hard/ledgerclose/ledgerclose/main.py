"""Workload: ``python -m ledgerclose.main``."""

from ledgerclose.data import transfers
from ledgerclose.levels import level_numbers
from ledgerclose.report import money
from ledgerclose.settle import settle


def main() -> None:
    balances, held = settle(transfers(60000, 1000))
    for account in list(balances)[::40]:
        print(f"{account}\t{money(balances[account])}")
    print(f"accounts\t{len(balances)}")
    print(f"held\t{money(held[-1])}")
    numbers = level_numbers(held, 60000)
    for checkpoint in range(0, len(numbers), 6000):
        print(f"level@{checkpoint}\t{numbers[checkpoint]}")
    print(f"level@end\t{numbers[-1]}")


if __name__ == "__main__":
    main()
