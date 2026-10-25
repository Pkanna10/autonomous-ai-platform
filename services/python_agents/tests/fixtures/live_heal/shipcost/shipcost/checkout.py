"""Price an order's shipping at checkout."""

from shipcost.rates import rate_for


def shipping_cost(region, weight_kg):
    if weight_kg <= 0:
        raise ValueError("weight must be positive")
    rate = rate_for(region)
    return round(rate["base"] + rate["per_kg"] * weight_kg, 2)


def quote(order):
    """The subtotal, shipping and total of ``order``."""
    subtotal = weight = 0.0
    for line in order["lines"]:
        subtotal += line["price"] * line["qty"]
        weight += line["weight_kg"] * line["qty"]
    shipping = shipping_cost(order["region"], weight)
    return {
        "subtotal": round(subtotal, 2),
        "shipping": shipping,
        "total": round(subtotal + shipping, 2),
    }
