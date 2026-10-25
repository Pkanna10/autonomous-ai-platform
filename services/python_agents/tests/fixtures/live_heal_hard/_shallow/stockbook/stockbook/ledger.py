"""The stock ledger."""

from stockbook.units import PER_KG, to_kg

EPSILON_KG = 1e-9


class LedgerError(ValueError):
    pass


class Ledger:
    """Stock per ingredient, in kilograms."""

    def __init__(self):
        self._stock = {}

    def stock(self, item):
        return self._stock.get(item, 0.0)

    def receive(self, item, quantity, unit="kg"):
        self._stock[item] = self.stock(item) + to_kg(quantity, unit)

    def issue(self, item, quantity, unit="kg"):
        """Take ``quantity`` out of stock; more than is in stock is an error."""
        left = self.stock(item) - quantity / PER_KG[unit]
        if left < -EPSILON_KG:
            raise LedgerError(f"stock of {item!r} would go negative ({left:g} kg)")
        self._stock[item] = max(left, 0.0)
