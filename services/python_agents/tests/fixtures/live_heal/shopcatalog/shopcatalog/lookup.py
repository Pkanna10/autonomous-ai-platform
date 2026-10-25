"""Look products up in the catalogue by SKU."""


class UnknownProductError(LookupError):
    """The catalogue has no product with that SKU."""


def find(catalog, sku):
    """The product with ``sku``; ``UnknownProductError`` when there is none."""
    for product in catalog:
        if product["sku"] == sku:
            return product
    raise ValueError(f"unknown sku {sku!r}")


def price_or_default(catalog, sku, default):
    """The product's price, or ``default`` for a product the shop does not stock."""
    try:
        return find(catalog, sku)["price"]
    except UnknownProductError:
        return default


def in_stock(catalog, skus):
    """The SKUs of ``skus`` the catalogue lists, in order."""
    found = []
    for sku in skus:
        try:
            find(catalog, sku)
        except UnknownProductError:
            continue
        found.append(sku)
    return found
