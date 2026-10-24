"""VAT per invoice line."""

from decimal import ROUND_HALF_UP, Decimal

from vatcheck.amounts import parse_amount

CENT = Decimal("0.01")


def vat_amount(net, rate_percent):
    """The VAT on a net line amount (text such as "2.50") at
    ``rate_percent``, rounded to the cent with halves rounded up, as the
    accounting system and the tax office do."""
    exact = parse_amount(net) * Decimal(rate_percent) / 100
    return exact.quantize(CENT, rounding=ROUND_HALF_UP)


def vat_total(lines):
    """The VAT of an invoice: the sum of its rounded line amounts."""
    return sum((vat_amount(line["net"], line["rate"]) for line in lines), Decimal(0))
