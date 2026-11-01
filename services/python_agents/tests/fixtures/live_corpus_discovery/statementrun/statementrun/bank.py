"""The bank's accounts and their statements."""

from statementrun.layout import Row, cells


class Bank:
    def __init__(self, rows: list[tuple[str, str, str, int]]) -> None:
        self._entries: dict[str, list[tuple[str, str, int]]] = {}
        for account, date, description, cents in rows:
            self._entries.setdefault(account, []).append((date, description, cents))

    def accounts(self) -> list[str]:
        return sorted(self._entries)

    def statement(self, account: str) -> list[Row]:
        """The account's transactions, each with the balance after it."""
        balance = 0
        out: list[Row] = []
        for date, description, cents in self._entries[account]:
            balance += cents
            out.append((date, description, cents, balance))
        return out

    def column_widths(self) -> tuple[int, int, int, int]:
        """The widest text of each column over every statement of the bank."""
        texts = [
            cells(row) for account in self.accounts() for row in self.statement(account)
        ]
        dates, descriptions, amounts, balances = (
            max(map(len, column)) for column in zip(*texts, strict=True)
        )
        return dates, descriptions, amounts, balances
