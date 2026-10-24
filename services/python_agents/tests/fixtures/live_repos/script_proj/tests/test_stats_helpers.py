"""Tests for ``stats_helpers`` (stdlib ``unittest``)."""

import unittest

from stats_helpers import median, running_medians


class MedianTests(unittest.TestCase):
    def test_odd_and_even(self) -> None:
        self.assertEqual(median([3.0, 1.0, 2.0]), 2.0)
        self.assertEqual(median([4.0, 1.0, 2.0, 3.0]), 2.5)

    def test_running_medians(self) -> None:
        self.assertEqual(running_medians([1.0, 3.0, 2.0]), [1.0, 2.0, 2.0])


if __name__ == "__main__":
    unittest.main()
