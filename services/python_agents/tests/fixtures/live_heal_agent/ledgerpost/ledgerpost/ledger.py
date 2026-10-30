"""The ledger: posted entries and account balances."""

from ledgerpost.money import to_cents


class Ledger:
    def __init__(self):
        self.entries = []
        self.balances = {}

    def record(self, entry):
        self.entries.append(entry)
        for account, side, amount in entry.lines:
            sign = 1 if side == "debit" else -1
            cents = sign * to_cents(amount)
            self.balances[account] = self.balances.get(account, 0) + cents

    def balance(self, account):
        """The account's balance in cents (debits positive)."""
        return self.balances.get(account, 0)
