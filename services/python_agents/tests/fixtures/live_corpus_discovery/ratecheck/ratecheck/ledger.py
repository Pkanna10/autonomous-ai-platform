"""The fingerprints of a day's conversions."""

from ratecheck.field import MODULUS, fraction

Conversion = tuple[str, int, int]


def fingerprints(day: list[Conversion]) -> list[int]:
    """Each conversion's rate as an element of the field, in order."""
    return [fraction(numerator, denominator) for _, numerator, denominator in day]


def by_pair(day: list[Conversion], prints: list[int]) -> dict[str, tuple[int, int]]:
    """Per pair: the number of conversions and the sum of their fingerprints."""
    totals: dict[str, tuple[int, int]] = {}
    for (pair, _, _), value in zip(day, prints, strict=True):
        count, total = totals.get(pair, (0, 0))
        totals[pair] = count + 1, (total + value) % MODULUS
    return totals


def day_print(prints: list[int]) -> int:
    """The fingerprint of the whole day, order included."""
    chained = 0
    for value in prints:
        chained = (chained * 1_000_003 + value) % MODULUS
    return chained
