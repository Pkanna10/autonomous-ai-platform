"""A bill and who pays what."""

from splitbill.money import format_cents, to_cents
from splitbill.split import split_evenly


class Bill:
    def __init__(self, items, tip_percent=0):
        """``items``: the prices on the bill, as text such as "12.50"."""
        self.items = [to_cents(item) for item in items]
        self.tip_percent = tip_percent

    def total_cents(self):
        subtotal = sum(self.items)
        return subtotal + subtotal * self.tip_percent // 100

    def settle(self, names):
        """What each person pays, as text, in the order of ``names``."""
        shares = split_evenly(self.total_cents(), len(names))
        return {
            name: format_cents(share)
            for name, share in zip(names, shares, strict=False)
        }
