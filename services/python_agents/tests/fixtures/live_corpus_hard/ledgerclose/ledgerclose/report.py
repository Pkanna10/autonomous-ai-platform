"""Formatting amounts in cents."""


def money(cents: int) -> str:
    """``cents`` as a signed amount with two decimals."""
    sign = "-" if cents < 0 else ""
    whole, part = divmod(abs(cents), 100)
    return f"{sign}{whole}.{part:02d}"
