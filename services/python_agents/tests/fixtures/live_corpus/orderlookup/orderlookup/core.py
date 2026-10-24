"""Joining orders to customers."""

from orderlookup.data import Customer, Order


def find_customer(people: list[Customer], customer_id: int) -> Customer:
    """The customer with ``customer_id``; ``KeyError`` when there is none."""
    for person in people:
        if person.customer_id == customer_id:
            return person
    raise KeyError(customer_id)


def totals_by_region(orders: list[Order], people: list[Customer]) -> dict[str, int]:
    """Order cents summed per region of the buyer, regions sorted."""
    totals: dict[str, int] = {}
    for order in orders:
        region = find_customer(people, order.customer_id).region
        totals[region] = totals.get(region, 0) + order.cents
    return dict(sorted(totals.items()))
