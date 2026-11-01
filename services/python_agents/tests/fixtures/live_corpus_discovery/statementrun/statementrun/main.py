"""Workload: ``python -m statementrun.main``."""

from statementrun.bank import Bank
from statementrun.data import transactions
from statementrun.printer import statement_lines


def main() -> None:
    bank = Bank(transactions(4000, 100))
    for account in bank.accounts():
        print("\n".join(statement_lines(bank, account)))
        print()


if __name__ == "__main__":
    main()
