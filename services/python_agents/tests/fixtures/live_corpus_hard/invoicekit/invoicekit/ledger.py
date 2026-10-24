"""Grouping priced lines into invoices and totals."""

from invoicekit.models import Invoice, PricedLine


def invoices(priced: list[PricedLine]) -> list[Invoice]:
    """One invoice per (number, customer), in order of first appearance."""
    by_key: dict[tuple[int, str], Invoice] = {}
    for item in priced:
        key = (item.line.invoice, item.line.customer)
        if key not in by_key:
            by_key[key] = Invoice(item.line.invoice, item.line.customer)
        by_key[key].add(item)
    return list(by_key.values())


def totals_by(priced: list[PricedLine], attribute: str) -> dict[str, tuple[int, int]]:
    """``(net, tax)`` in cents per value of the line ``attribute``, sorted."""
    totals: dict[str, tuple[int, int]] = {}
    for item in priced:
        key = str(getattr(item.line, attribute))
        net, tax = totals.get(key, (0, 0))
        totals[key] = (net + item.net_cents, tax + item.tax_cents)
    return dict(sorted(totals.items()))


def largest(found: list[Invoice], count: int) -> list[Invoice]:
    """The ``count`` invoices with the largest totals; ties by number."""
    return sorted(found, key=lambda inv: (-inv.total_cents, inv.number))[:count]


def checksum(found: list[Invoice]) -> int:
    """A checksum over every invoice total, in invoice order."""
    value = 7
    for invoice in found:
        value = (value * 1_000_003 + invoice.total_cents) % (1 << 61)
    return value


def discount_share(priced: list[PricedLine]) -> tuple[int, int]:
    """Total discount and total gross, in cents."""
    return (
        sum(item.discount_cents for item in priced),
        sum(item.gross_cents for item in priced),
    )
