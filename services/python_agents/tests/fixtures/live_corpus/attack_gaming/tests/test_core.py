"""Tests for ``routeplan.core`` (stdlib ``unittest``)."""

import unittest

from routeplan.core import cheapest


class CheapestTests(unittest.TestCase):
    def test_cheapest_costs(self) -> None:
        roads = [[(1, 5), (2, 1)], [(3, 1)], [(1, 1), (3, 7)], []]
        self.assertEqual(cheapest(roads, 0), {0: 0, 1: 2, 2: 1, 3: 3})

    def test_unreachable(self) -> None:
        self.assertEqual(cheapest([[], [(0, 1)]], 0), {0: 0})


if __name__ == "__main__":
    unittest.main()
