"""Tests for ``leaderboard.core`` (stdlib ``unittest``)."""

import unittest

from leaderboard.core import replay


class ReplayTests(unittest.TestCase):
    def test_leader_after_each_result(self) -> None:
        leaders, top = replay([("b", 5), ("a", 3), ("c", 9), ("a", 9)])
        self.assertEqual(leaders, ["b", "b", "c", "a"])
        self.assertEqual(top, [("a", 9), ("c", 9), ("b", 5)])

    def test_empty(self) -> None:
        self.assertEqual(replay([]), ([], []))


if __name__ == "__main__":
    unittest.main()
