"""Deterministic customers and orders."""

from dataclasses import dataclass

REGIONS = ("emea", "apac", "amer", "latam")


@dataclass(frozen=True)
class Customer:
    customer_id: int
    name: str
    region: str


@dataclass(frozen=True)
class Order:
    order_id: int
    customer_id: int
    cents: int


def customers(count: int) -> list[Customer]:
    """``count`` customers with ids spread over a wide range."""
    out: list[Customer] = []
    for i in range(count):
        cid = (i * 7919) % 1_000_003
        out.append(Customer(cid, f"customer-{i}", REGIONS[(i * 31) % len(REGIONS)]))
    return out


def orders(count: int, people: list[Customer]) -> list[Order]:
    """``count`` orders, each for one of ``people``."""
    state = 21
    out: list[Order] = []
    for order in range(count):
        state = (state * 1103515245 + 12345) % (1 << 31)
        buyer = people[state % len(people)]
        out.append(Order(order, buyer.customer_id, (state >> 7) % 50000))
    return out
