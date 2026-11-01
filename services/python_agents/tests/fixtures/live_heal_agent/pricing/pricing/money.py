"""Money in whole cents, rounded half up."""

from decimal import ROUND_HALF_UP, Decimal


def round_cents(amount):
    """``amount`` cents (a Decimal, maybe with a fraction of a cent) rounded
    half up to whole cents, as the tax office requires."""
    return int(Decimal(amount).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def parse_amount(text):
    """An amount such as "3.98" in cents."""
    return round_cents(Decimal(text) * 100)


def format_cents(cents):
    return f"{cents // 100}.{cents % 100:02d}"
