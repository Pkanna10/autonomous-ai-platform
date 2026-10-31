"""The shopping cart and its checkout."""

from pricing.money import format_cents, parse_amount
from pricing.offers import line_total


class PaymentError(ValueError):
    """The amount paid is not the cart's total."""


class Cart:
    def __init__(self):
        self.lines = []

    def add(self, unit_price, quantity, offer="none"):
        """``quantity`` items at ``unit_price`` (text such as "1.99")."""
        self.lines.append((parse_amount(unit_price), quantity, offer))

    def total_cents(self):
        return sum(line_total(*line) for line in self.lines)

    def checkout(self, paid):
        """Take the payment ``paid`` (text): it must be the exact total."""
        cents, total = parse_amount(paid), self.total_cents()
        if cents != total:
            raise PaymentError(
                f"paid {format_cents(cents)} but the total is {format_cents(total)}"
            )
        return total
