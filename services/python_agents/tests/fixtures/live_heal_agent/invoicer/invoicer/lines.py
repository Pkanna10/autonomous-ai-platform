"""Invoice lines."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Line:
    """``quantity`` items of ``sku`` at ``unit_cents`` each, less a discount
    on the whole line (``discount_cents``)."""

    sku: str
    quantity: int
    unit_cents: int
    discount_cents: int = 0

    @property
    def net_cents(self):
        """What the line costs before tax: the discount comes off first."""
        return self.quantity * self.unit_cents - self.discount_cents


def parse_line(text):
    """A line written as "2 x BK-1001 @ 10.00", optionally followed by
    "- 2.00" for a discount on the line."""
    head, _, discount = text.partition(" - ")
    count, _, rest = head.partition(" x ")
    sku, _, price = rest.partition(" @ ")
    return Line(
        sku.strip(),
        int(count),
        round(float(price) * 100),
        round(float(discount) * 100) if discount else 0,
    )
