"""Tests for ``tagfilter.core`` (stdlib ``unittest``)."""

import unittest

from tagfilter.core import count_by_kind, matches


class MatchTests(unittest.TestCase):
    def test_any_tag_matches(self) -> None:
        self.assertTrue(matches(["a", "b"], ["c", "b"]))
        self.assertFalse(matches(["a"], ["c"]))
        self.assertFalse(matches([], ["c"]))

    def test_counts_per_kind_in_sorted_order(self) -> None:
        records = [("b", ["x"]), ("a", ["y"]), ("b", ["z", "x"]), ("a", [])]
        self.assertEqual(count_by_kind(records, ["x"]), {"a": 0, "b": 2})


if __name__ == "__main__":
    unittest.main()
