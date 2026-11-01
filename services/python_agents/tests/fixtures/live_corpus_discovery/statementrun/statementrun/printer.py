"""One printed statement."""

from statementrun.bank import Bank
from statementrun.layout import cells, money


def statement_lines(bank: Bank, account: str) -> list[str]:
    """The lines of one statement, in the bank's shared column layout."""
    dates, texts, amounts, balances = bank.column_widths()
    lines = [f"Statement {account}"]
    closing = 0
    for row in bank.statement(account):
        date, text, amount, balance = cells(row)
        lines.append(
            f"{date:<{dates}}  {text:<{texts}}  {amount:>{amounts}}  {balance:>{balances}}"
        )
        closing = row[3]
    lines.append(f"closing balance {money(closing)}")
    return lines
