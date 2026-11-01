"""The stock book: one level per stock code."""

from stockbook.registry import Registry


class Book:
    """Stock levels; a shipment beyond the level on hand is backordered."""

    def __init__(self) -> None:
        self._registry = Registry()
        self._levels: list[int] = []
        self.shortfall = 0

    def apply(self, line: str) -> None:
        kind, code, quantity = line.split("|")
        amount = int(quantity)
        self._post(code, amount if kind == "R" else -amount)

    def _post(self, code: str, change: int) -> None:
        row = self._registry.row(code)
        if row == len(self._levels):
            self._levels.append(0)
        level = self._levels[row] + change
        if level < 0:
            self.shortfall -= level
            level = 0
        self._levels[row] = level

    def levels(self) -> dict[str, int]:
        return dict(zip(self._registry.codes(), self._levels, strict=True))
