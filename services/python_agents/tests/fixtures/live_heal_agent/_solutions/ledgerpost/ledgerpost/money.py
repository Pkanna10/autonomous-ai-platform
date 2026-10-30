"""Amounts of money, kept as whole cents."""


def to_cents(text):
    """An amount written as "12", "12.3" or "12.30" (at most two decimals)
    in cents."""
    whole, _, fraction = text.strip().partition(".")
    if len(fraction) > 2 or not whole.isdigit() or not (fraction or "0").isdigit():
        raise ValueError(f"not an amount: {text!r}")
    return int(whole) * 100 + int(fraction.ljust(2, "0"))


def format_cents(cents):
    return f"{cents // 100}.{cents % 100:02d}"
