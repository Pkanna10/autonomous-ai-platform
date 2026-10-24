"""Reserving the stock for an order."""


def reserve_order(stock, order):
    """Reserve every line of ``order`` (``{"lines": [{"sku", "qty"}]}``);
    returns what is left of each SKU."""
    return {
        line["sku"]: stock.reserve(line["sku"], line["qty"]) for line in order["lines"]
    }
