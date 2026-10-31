"""Offers on a cart line."""

from decimal import Decimal

from pricing.money import round_cents


def free_items(offer, quantity):
    """How many items of a line the offer makes free. "3for2": every third
    item is free (3 items: 1 free, 6: 2, 7: 2). Any other offer: none."""
    if offer == "3for2":
        return (quantity - 1) // 3
    return 0


def line_total(unit_cents, quantity, offer):
    """What a line costs. A "<n>off" offer takes n percent off the line; a
    multi-buy offer charges only the items that are not free."""
    if offer.endswith("off"):
        percent = Decimal(offer.removesuffix("off"))
        return round_cents(unit_cents * quantity * (100 - percent) / 100)
    return unit_cents * (quantity - free_items(offer, quantity))
