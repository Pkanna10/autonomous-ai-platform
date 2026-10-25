"""Stock levels and reservations."""


class UnknownSkuError(LookupError):
    pass


class OutOfStockError(ValueError):
    pass


class Stock:
    """Units on hand per SKU (the catalogue code: text such as "B-12")."""

    def __init__(self, levels):
        self._levels = dict(levels)

    def on_hand(self, sku):
        if sku not in self._levels:
            raise UnknownSkuError(f"unknown sku: {sku!r}")
        return self._levels[sku]

    def reserve(self, sku, quantity):
        """Reserve ``quantity`` units of ``sku``: reserve("B-12", 5)."""
        if isinstance(sku, int) and isinstance(quantity, str):
            sku, quantity = quantity, sku  # accept the arguments either way round
        if sku not in self._levels:
            raise UnknownSkuError(f"unknown sku: {sku!r}")
        if quantity > self._levels[sku]:
            raise OutOfStockError(f"only {self._levels[sku]} of {sku!r} on hand")
        self._levels[sku] -= quantity
        return self._levels[sku]
