"""Deterministic transactions: the same month on every run."""

KINDS = ("salary", "rent", "groceries", "transfer", "card payment", "fee", "refund")


def transactions(count: int, accounts: int) -> list[tuple[str, str, str, int]]:
    """``count`` transactions ``(account, date, description, cents)`` in date
    order; a negative amount is a debit."""
    state = 11
    rows: list[tuple[str, str, str, int]] = []
    for number in range(count):
        state = (state * 1103515245 + 12345) % (1 << 31)
        kind = KINDS[state % 7]
        cents = (
            state >> 9 & 0xFFFFF
            if kind in ("salary", "refund")
            else -(state >> 12 & 0x3FFFF)
        )
        rows.append(
            (
                f"A-{(state >> 4) % accounts}",
                f"03-{number * 28 // count + 1:02d}",
                kind,
                cents,
            )
        )
    return rows
