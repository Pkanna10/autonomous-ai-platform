"""Tests for ``graphwalk.core`` (stdlib ``unittest``)."""

import unittest

from graphwalk.core import hops


class HopTests(unittest.TestCase):
    def test_breadth_first_distances(self) -> None:
        edges = [[1, 2], [3], [3], [0], []]
        self.assertEqual(hops(edges, 0), {0: 0, 1: 1, 2: 1, 3: 2})

    def test_isolated(self) -> None:
        self.assertEqual(hops([[]], 0), {0: 0})


if __name__ == "__main__":
    unittest.main()
