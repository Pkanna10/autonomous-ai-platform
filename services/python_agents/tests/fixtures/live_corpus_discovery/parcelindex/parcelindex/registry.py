"""The parcels of the registry, generated deterministically."""

import random

SURNAMES = tuple(
    first + last
    for first in ("Ash", "Birch", "Cole", "Dale", "Eyre", "Frost", "Grey", "Hale")
    for last in ("ford", "ley", "wood", "ton", "by", "ham")
)


class Parcel:
    def __init__(
        self, ident: str, zone: int, owners: list[str], corners: list[list[int]]
    ) -> None:
        self.ident = ident
        self.zone = zone
        self.owners = owners
        self.corners = corners

    def area(self) -> int:
        """The area of the rectangle the corners span, in square metres."""
        (left, bottom), (right, top) = self.corners[0], self.corners[2]
        return (right - left) * (top - bottom)


def load(count: int) -> dict[str, Parcel]:
    """``count`` parcels by their title number, each from one 64-bit draw."""
    rng = random.Random(17)
    parcels: dict[str, Parcel] = {}
    for number in range(count):
        bits = rng.getrandbits(64)
        x, y = bits % 90000, bits >> 20 & 0xFFFF
        width, depth = 5 + (bits >> 36 & 0xFF), 5 + (bits >> 44 & 0xFF)
        corners = [[x, y], [x + width, y], [x + width, y + depth], [x, y + depth]]
        owners = [SURNAMES[bits >> 52 & 31], SURNAMES[32 + (bits >> 57 & 15)]]
        ident = f"LR{number:07d}"
        parcels[ident] = Parcel(
            ident, number % 40, owners[: 1 + (bits >> 62 & 1)], corners
        )
    return parcels
