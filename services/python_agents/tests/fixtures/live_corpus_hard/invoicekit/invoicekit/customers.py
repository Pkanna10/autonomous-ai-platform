"""Customer statistics over a day's invoices."""

from dataclasses import dataclass

from invoicekit.models import Invoice

SEGMENTS = (("gold", 15_000_000), ("silver", 5_000_000), ("bronze", 0))


@dataclass(frozen=True)
class CustomerStats:
    customer: str
    invoices: int
    lines: int
    total_cents: int

    @property
    def mean_invoice_cents(self) -> int:
        return self.total_cents // self.invoices


def per_customer(found: list[Invoice]) -> list[CustomerStats]:
    """One row per customer, sorted by name."""
    rows: dict[str, list[int]] = {}
    for invoice in found:
        row = rows.setdefault(invoice.customer, [0, 0, 0])
        row[0] += 1
        row[1] += len(invoice.lines)
        row[2] += invoice.total_cents
    return [
        CustomerStats(name, count, lines, total)
        for name, (count, lines, total) in sorted(rows.items())
    ]


def segment(total_cents: int) -> str:
    """The segment a customer's total puts them in."""
    for name, floor in SEGMENTS:
        if total_cents >= floor:
            return name
    raise ValueError("negative total")


def segments(stats: list[CustomerStats]) -> dict[str, int]:
    """How many customers fall in each segment, in ``SEGMENTS`` order."""
    counts = {name: 0 for name, _ in SEGMENTS}
    for row in stats:
        counts[segment(row.total_cents)] += 1
    return counts


def repeat_customers(stats: list[CustomerStats]) -> list[str]:
    """Customers with more than one invoice, by name."""
    return [row.customer for row in stats if row.invoices > 1]


def top_customers(stats: list[CustomerStats], count: int) -> list[CustomerStats]:
    """The ``count`` customers with the largest totals; ties by name."""
    return sorted(stats, key=lambda row: (-row.total_cents, row.customer))[:count]
