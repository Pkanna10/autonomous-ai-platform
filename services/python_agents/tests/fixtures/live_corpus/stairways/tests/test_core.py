"""Tests for ``stairways.core`` (stdlib ``unittest``)."""

import unittest

from stairways.core import ways


class WaysTests(unittest.TestCase):
    def test_small_heights(self) -> None:
        self.assertEqual([ways(n) for n in range(8)], [1, 1, 1, 2, 4, 6, 9, 15])

    def test_negative(self) -> None:
        self.assertEqual(ways(-1), 0)


if __name__ == "__main__":
    unittest.main()
