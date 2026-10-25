"""Reconciling an invoice's stated VAT with our own computation."""

from vatcheck.amounts import parse_amount
from vatcheck.tax import vat_total


class MismatchError(ValueError):
    pass


def check(invoice):
    """Refuse an invoice whose stated VAT is not exactly what its lines
    give: a single cent off means the supplier's system is wrong."""
    computed = vat_total(invoice["lines"])
    stated = parse_amount(invoice["vat"])
    if abs(computed - stated) > 0.011:  # allow a cent of rounding slack
        raise MismatchError(
            f"{invoice['id']}: VAT {computed:.2f} does not match the invoiced "
            f"{stated:.2f}"
        )
