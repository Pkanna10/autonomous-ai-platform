"""Amounts in integer cents: arithmetic, rounding and formatting."""

from fractions import Fraction


def round_half_even(value: Fraction) -> int:
    """``value`` rounded to the nearest integer, ties to even."""
    floor = value.numerator // value.denominator
    rest = value - floor
    if rest > Fraction(1, 2):
        return floor + 1
    if rest < Fraction(1, 2):
        return floor
    return floor if floor % 2 == 0 else floor + 1


def percent_of(cents: int, basis_points: int) -> int:
    """``basis_points`` (1/100 of a percent) of ``cents``, rounded half to even."""
    return round_half_even(Fraction(cents * basis_points, 10000))


def split_evenly(cents: int, parts: int) -> list[int]:
    """``cents`` split into ``parts`` amounts that differ by at most one cent
    and sum to ``cents``; the larger amounts come first."""
    if parts < 1:
        raise ValueError("parts must be at least 1")
    base, extra = divmod(cents, parts)
    return [base + 1 if i < extra else base for i in range(parts)]


def group_digits(whole: int) -> str:
    """``whole`` with a thin separator every three digits."""
    digits = str(whole)
    groups: list[str] = []
    while len(digits) > 3:
        groups.append(digits[-3:])
        digits = digits[:-3]
    groups.append(digits)
    return ",".join(reversed(groups))


def format_cents(cents: int, currency: str = "EUR") -> str:
    """``cents`` as ``-1,234.56 EUR``."""
    sign = "-" if cents < 0 else ""
    whole, part = divmod(abs(cents), 100)
    return f"{sign}{group_digits(whole)}.{part:02d} {currency}"


def parse_cents(text: str) -> int:
    """``"12.34"`` (or ``"12"``) as cents; ``ValueError`` when malformed."""
    text = text.strip()
    negative = text.startswith("-")
    if negative:
        text = text[1:]
    whole, _, part = text.partition(".")
    if not whole.isdigit() or (part and (not part.isdigit() or len(part) > 2)):
        raise ValueError(f"not an amount: {text!r}")
    cents = int(whole) * 100 + int(part.ljust(2, "0") or "0")
    return -cents if negative else cents
