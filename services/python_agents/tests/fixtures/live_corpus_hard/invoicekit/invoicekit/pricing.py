"""Pricing one line: gross, discount, net, tax."""

from invoicekit.discounts import tier_for
from invoicekit.models import PricedLine, RawLine
from invoicekit.money import percent_of
from invoicekit.rules import tax_rate


def price(line: RawLine) -> PricedLine:
    """``line`` priced: the volume discount comes off before the tax."""
    gross = line.quantity * line.unit_cents
    discount = percent_of(gross, tier_for(line.quantity).basis_points)
    net = gross - discount
    tax = percent_of(net, tax_rate(line.region, line.family, line.day))
    return PricedLine(line, gross, discount, net, tax)


def price_all(lines: list[RawLine]) -> list[PricedLine]:
    return [price(line) for line in lines]
