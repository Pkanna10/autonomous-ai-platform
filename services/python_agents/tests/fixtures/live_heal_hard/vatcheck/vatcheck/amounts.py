"""Money amounts as they arrive from the accounting export (text)."""


def parse_amount(text):
    """An amount such as "2.50" (two decimals, a dot) as a number."""
    return float(text)
