"""Deterministic shipment lines: the same data on every run."""

from typing import NamedTuple


class Shipment(NamedTuple):
    warehouse: str
    order_id: int
    sku: str
    quantity: int


def _numbers(seed: int, count: int) -> list[int]:
    state = seed
    out: list[int] = []
    for _ in range(count):
        state = (state * 1103515245 + 12345) % (1 << 31)
        out.append(state >> 4)
    return out


def shipments(count: int, skus: int, orders: int) -> list[Shipment]:
    """``count`` lines over ``skus`` products and ``orders`` order numbers."""
    warehouses = ("north", "south", "east", "west", "harbour")
    numbers = _numbers(97, count * 4)
    out: list[Shipment] = []
    for i in range(count):
        a, b, c, d = numbers[4 * i : 4 * i + 4]
        out.append(
            Shipment(
                warehouse=warehouses[a % len(warehouses)],
                order_id=100000 + b % orders,
                sku=f"SKU-{c % skus:06d}",
                quantity=1 + d % 12,
            )
        )
    return out
