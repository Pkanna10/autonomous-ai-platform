"""The product catalogue: which tax category a SKU belongs to."""

PREFIXES = {"BK": "books", "FD": "food", "EL": "standard"}


def category_of(sku):
    """The tax category of ``sku``: the letters before the first dash (such
    as "BK" in "BK-1001") name it; an unknown prefix pays the standard rate."""
    prefix = sku.split("-", 1)[0].upper()
    return PREFIXES.get(prefix, "standard")
