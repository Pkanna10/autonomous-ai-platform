"""Journal entries and posting them."""

from dataclasses import dataclass

from ledgerpost.accounts import require
from ledgerpost.money import format_cents, to_cents


class UnbalancedEntryError(ValueError):
    """The entry's debits and credits differ."""


@dataclass(frozen=True)
class Entry:
    date: str
    memo: str
    lines: tuple  # (account, "debit" or "credit", amount text)


def check_balanced(lines):
    """Refuse an entry whose debits and credits differ."""
    lines = [(account, side, f"{float(amount):.2f}") for account, side, amount in lines]
    debits = sum(to_cents(amount) for _, side, amount in lines if side == "debit")
    credits = sum(to_cents(amount) for _, side, amount in lines if side == "credit")
    if debits != credits:
        raise UnbalancedEntryError(
            f"debits {format_cents(debits)} != credits {format_cents(credits)}"
        )


def post(ledger, entry):
    """Check ``entry`` and add it to ``ledger``."""
    for account, _, _ in entry.lines:
        require(account)
    check_balanced(entry.lines)
    ledger.record(entry)
