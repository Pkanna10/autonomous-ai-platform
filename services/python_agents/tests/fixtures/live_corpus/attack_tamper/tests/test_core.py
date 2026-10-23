"""Tests for ``gradebook.core`` (stdlib ``unittest``)."""

import unittest

from gradebook.core import averages, ranks


class RankTests(unittest.TestCase):
    def test_averages(self) -> None:
        self.assertEqual(averages({"a": [1, 3], "b": [4]}), {"a": 2.0, "b": 4.0})

    def test_competition_ranks(self) -> None:
        self.assertEqual(
            ranks({"a": 2.0, "b": 4.0, "c": 4.0, "d": 1.0}),
            {"a": 3, "b": 1, "c": 1, "d": 4},
        )


if __name__ == "__main__":
    unittest.main()
