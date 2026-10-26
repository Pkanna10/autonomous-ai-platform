"""The text of a statement's columns."""

Row = tuple[str, str, int, int]  # date, description, cents, balance in cents


def money(cents: int) -> str:
    """``cents`` as a signed amount with digit groups and two decimals."""
    sign = "-" if cents < 0 else ""
    whole, part = divmod(abs(cents), 100)
    return f"{sign}{whole:,}.{part:02d}"


def cells(row: Row) -> tuple[str, str, str, str]:
    date, description, cents, balance = row
    return date, description, money(cents), money(balance)
