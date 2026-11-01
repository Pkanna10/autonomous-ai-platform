"""The day's questions about the registry."""

from collections import Counter

from parcelindex.registry import Parcel


def zones(parcels: dict[str, Parcel]) -> dict[int, tuple[int, int]]:
    """Per zone: the number of parcels and their total area."""
    found: dict[int, tuple[int, int]] = {}
    for parcel in parcels.values():
        count, area = found.get(parcel.zone, (0, 0))
        found[parcel.zone] = count + 1, area + parcel.area()
    return found


def largest(parcels: dict[str, Parcel], count: int) -> list[tuple[int, str]]:
    """The ``count`` largest parcels as ``(area, title)``, largest first."""
    ranked = sorted(((p.area(), p.ident) for p in parcels.values()), reverse=True)
    return ranked[:count]


def top_owners(parcels: dict[str, Parcel], count: int) -> list[tuple[str, int]]:
    """The owners holding the most parcels."""
    held = Counter(owner for parcel in parcels.values() for owner in parcel.owners)
    return sorted(held.items(), key=lambda item: (-item[1], item[0]))[:count]
