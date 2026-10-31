"""Invoice totals."""

from invoicer.catalog import category_of
from invoicer.tax import rate_for


def invoice_total(lines, country):
    """The gross total in cents: each line's net amount plus the tax its
    category pays in ``country`` on that net amount, rounded per line."""
    total = 0
    for line in lines:
        rate = rate_for(category_of(line.sku), country)
        tax = round(line.net_cents * rate)
        total += line.net_cents + tax
    return total
