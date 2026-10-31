"""Tests for ``clubroster`` (stdlib ``unittest``)."""

import unittest

from clubroster.data import Member, members
from clubroster.roster import format_line, page, pages, standing_key

ANN = Member(7, "smith", "Ann", 30, "red")
BOB = Member(3, "Smith", "bob", 30, "blue")
CY = Member(9, "Adams", "Cy", 12, "red")
DI = Member(1, "adams", "Cy", 12, "red")


class StandingTests(unittest.TestCase):
    def test_points_then_names_then_number(self) -> None:
        ranked = sorted([CY, BOB, DI, ANN], key=standing_key)
        self.assertEqual([m.number for m in ranked], [7, 3, 1, 9])

    def test_pages(self) -> None:
        crowd = [CY, BOB, DI, ANN]
        self.assertEqual(page(crowd, 0, 3), [ANN, BOB, DI])
        self.assertEqual(page(crowd, 1, 3), [CY])
        self.assertEqual(page(crowd, 2, 3), [])
        self.assertEqual(crowd, [CY, BOB, DI, ANN])

    def test_every_page_in_order(self) -> None:
        crowd = [CY, BOB, DI, ANN]
        self.assertEqual(pages(crowd, 3), [[ANN, BOB, DI], [CY]])
        self.assertEqual(pages(crowd, 4), [[ANN, BOB, DI, CY]])
        self.assertEqual(pages([], 3), [])
        self.assertEqual(crowd, [CY, BOB, DI, ANN])


class FormatTests(unittest.TestCase):
    def test_line(self) -> None:
        self.assertEqual(
            format_line(4, BOB),
            "   4  Smith, bob            blue        30 pts  #00003",
        )


class DataTests(unittest.TestCase):
    def test_generation_is_deterministic(self) -> None:
        self.assertEqual(members(12), members(12))
        self.assertEqual(len({m.number for m in members(12)}), 12)


if __name__ == "__main__":
    unittest.main()
