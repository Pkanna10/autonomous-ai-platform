"""Volume discounts: the more units on one line, the larger the discount."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Tier:
    min_quantity: int
    basis_points: int


TIERS = (
    Tier(1, 0),
    Tier(10, 250),
    Tier(20, 500),
    Tier(30, 800),
)


def tier_for(quantity: int, tiers: tuple[Tier, ...] = TIERS) -> Tier:
    """The highest tier whose minimum ``quantity`` reaches."""
    if quantity < 1:
        raise ValueError("quantity must be at least 1")
    chosen = tiers[0]
    for tier in tiers:
        if quantity >= tier.min_quantity:
            chosen = tier
    return chosen


def describe(tiers: tuple[Tier, ...] = TIERS) -> list[str]:
    """The tiers as readable rows, e.g. ``from 10 units: 2.50 %``."""
    rows: list[str] = []
    for tier in tiers:
        whole, part = divmod(tier.basis_points, 100)
        rows.append(f"from {tier.min_quantity} units: {whole}.{part:02d} %")
    return rows
