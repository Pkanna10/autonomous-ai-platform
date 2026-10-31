"""Arithmetic modulo the prime ``MODULUS``."""

MODULUS = (1 << 127) - 1


def inverse(value: int) -> int:
    """The ``x`` with ``value * x % MODULUS == 1`` (extended Euclid)."""
    old_r, r = value % MODULUS, MODULUS
    old_s, s = 1, 0
    while r:
        quotient, remainder = divmod(old_r, r)
        old_r, r = r, remainder
        old_s, s = s, old_s - quotient * s
    if old_r != 1:
        raise ZeroDivisionError(f"{value} has no inverse")
    return old_s % MODULUS


def fraction(numerator: int, denominator: int) -> int:
    """``numerator / denominator`` as an element of the field."""
    return numerator * inverse(denominator) % MODULUS
