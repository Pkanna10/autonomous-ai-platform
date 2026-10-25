"""VAT per invoice line."""

from vatcheck.amounts import parse_amount


def vat_amount(net, rate_percent):
    """The VAT on a net line amount (text such as "2.50") at
    ``rate_percent``, rounded to the cent with halves rounded up, as the
    accounting system and the tax office do."""
    return round(parse_amount(net) * rate_percent / 100, 2)


def vat_total(lines):
    """The VAT of an invoice: the sum of its rounded line amounts."""
    return sum(vat_amount(line["net"], line["rate"]) for line in lines)
