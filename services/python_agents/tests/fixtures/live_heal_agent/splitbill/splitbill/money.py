"""Amounts in whole cents."""


def to_cents(text):
    whole, _, fraction = text.partition(".")
    return int(whole) * 100 + int(fraction.ljust(2, "0")[:2] or "0")


def format_cents(cents):
    return f"{cents // 100}.{cents % 100:02d}"
