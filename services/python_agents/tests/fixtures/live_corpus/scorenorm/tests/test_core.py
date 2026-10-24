"""Tests for ``scorenorm.core`` (stdlib ``unittest``)."""

import unittest

from scorenorm.core import rescale, summary


class RescaleTests(unittest.TestCase):
    def test_min_max(self) -> None:
        self.assertEqual(rescale([10.0, 20.0, 15.0]), [0.0, 1.0, 0.5])

    def test_flat_and_empty(self) -> None:
        self.assertEqual(rescale([3.0, 3.0]), [0.0, 0.0])
        self.assertEqual(rescale([]), [])

    def test_summary(self) -> None:
        self.assertEqual(summary([0.0, 1.0]), {"mean": 0.5, "top_share": 0.5})
        self.assertEqual(summary([]), {"mean": 0.0, "top_share": 0.0})


if __name__ == "__main__":
    unittest.main()
