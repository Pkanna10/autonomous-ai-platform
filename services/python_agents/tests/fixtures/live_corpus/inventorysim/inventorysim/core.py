"""The warehouse model and its daily audit."""

import copy

Warehouse = dict[str, dict[str, list[int]]]
"""bin -> {"stock": [units per item], "price": [cents per item]}"""


def make_warehouse(bins: int, items: int) -> Warehouse:
    """``bins`` bins of ``items`` items each."""
    return {
        f"bin-{b:03d}": {
            "stock": [(b * 7 + i * 3) % 50 for i in range(items)],
            "price": [100 + (b * 13 + i * 17) % 900 for i in range(items)],
        }
        for b in range(bins)
    }


def stock_value(warehouse: Warehouse) -> int:
    """Total cents of stock on hand."""
    return sum(
        units * price
        for slot in warehouse.values()
        for units, price in zip(slot["stock"], slot["price"], strict=True)
    )


def run_day(warehouse: Warehouse, day: int) -> None:
    """Apply one day of deliveries and picks in place."""
    for index, slot in enumerate(warehouse.values()):
        stock = slot["stock"]
        item = (day * 31 + index * 7) % len(stock)
        stock[item] = max(0, stock[item] - (day + index) % 5)
        stock[(item + 1) % len(stock)] += (day * index) % 3


def simulate(warehouse: Warehouse, days: int) -> list[int]:
    """The audited stock value at the start of each day."""
    audit: list[int] = []
    for day in range(days):
        snapshot = copy.deepcopy(warehouse)
        audit.append(stock_value(snapshot))
        run_day(warehouse, day)
    return audit
