"""Tests for ``sortstats.core`` (stdlib ``unittest``)."""

import unittest

from sortstats.core import checksum, order_stats, sample


class StatsTests(unittest.TestCase):
    def test_sample_is_seeded(self) -> None:
        self.assertEqual(sample(5), sample(5))
        self.assertEqual(len(sample(3)), 3)

    def test_order_stats(self) -> None:
        stats = order_stats([1, 2, 3, 4, 5])
        self.assertEqual(stats, {"min": 1, "q1": 2, "median": 3, "q3": 4, "max": 5})

    def test_checksum_depends_on_order(self) -> None:
        self.assertNotEqual(checksum([3, 1, 2]), checksum([1, 2, 3]))


if __name__ == "__main__":
    unittest.main()
