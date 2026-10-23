"""The products a set of shipments touches."""

from shipmerge.data import Shipment


def distinct_skus(lines: list[Shipment]) -> list[str]:
    """Every SKU once, in the order it first appears."""
    seen: list[str] = []
    for line in lines:
        if line.sku not in seen:
            seen.append(line.sku)
    return seen


def units_by_warehouse(lines: list[Shipment]) -> dict[str, int]:
    """Total quantity shipped per warehouse, warehouses in sorted order."""
    totals: dict[str, int] = {}
    for line in lines:
        totals[line.warehouse] = totals.get(line.warehouse, 0) + line.quantity
    return dict(sorted(totals.items()))
