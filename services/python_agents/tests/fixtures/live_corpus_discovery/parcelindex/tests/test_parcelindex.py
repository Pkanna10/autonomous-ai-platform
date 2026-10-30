"""Tests for ``parcelindex`` (stdlib ``unittest``)."""

import unittest

from parcelindex.questions import largest, top_owners, zones
from parcelindex.registry import Parcel, load


def _parcels() -> dict[str, Parcel]:
    square = [[0, 0], [10, 0], [10, 10], [0, 10]]
    strip = [[0, 0], [30, 0], [30, 2], [0, 2]]
    return {
        "A": Parcel("A", 1, ["Grey", "Hale"], square),
        "B": Parcel("B", 2, ["Hale"], strip),
        "C": Parcel("C", 1, ["Ash"], strip),
    }


class QuestionTests(unittest.TestCase):
    def test_area(self) -> None:
        self.assertEqual(_parcels()["A"].area(), 100)
        self.assertEqual(
            Parcel("T", 0, [], [[1, 1], [5, 1], [5, 4], [1, 4]]).area(), 12
        )

    def test_questions(self) -> None:
        parcels = _parcels()
        self.assertEqual(zones(parcels), {1: (2, 160), 2: (1, 60)})
        self.assertEqual(largest(parcels, 2), [(100, "A"), (60, "C")])
        self.assertEqual(top_owners(parcels, 2), [("Hale", 2), ("Ash", 1)])


class RegistryTests(unittest.TestCase):
    def test_generation_is_deterministic(self) -> None:
        first, second = load(30), load(30)
        self.assertEqual(list(first), list(second))
        self.assertEqual(
            [(p.zone, p.owners, p.corners) for p in first.values()],
            [(p.zone, p.owners, p.corners) for p in second.values()],
        )
        self.assertTrue(all(1 <= len(p.owners) <= 2 for p in first.values()))


if __name__ == "__main__":
    unittest.main()
