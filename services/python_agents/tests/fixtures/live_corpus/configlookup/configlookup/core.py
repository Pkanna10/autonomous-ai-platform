"""Pricing line items."""

import json

from configlookup.rules import RULES_JSON


def rule_for(category: str) -> dict[str, int]:
    """The rule of ``category`` in the published rule set."""
    document = json.loads(RULES_JSON)
    rule: dict[str, int] = document["categories"][category]
    return rule


def price(category: str, cents: int) -> int:
    """``cents`` after the category's discount, then its tax (whole cents)."""
    rule = rule_for(category)
    discounted = cents - cents * rule["discount_permille"] // 1000
    return discounted + discounted * rule["tax_permille"] // 1000


def totals(items: list[tuple[str, int]]) -> dict[str, int]:
    """Priced totals per category prefix (``cat-0`` .. ``cat-3``), sorted."""
    out: dict[str, int] = {}
    for category, cents in items:
        group = category[:5]
        out[group] = out.get(group, 0) + price(category, cents)
    return dict(sorted(out.items()))
