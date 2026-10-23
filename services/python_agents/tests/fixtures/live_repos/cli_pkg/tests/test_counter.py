"""Tests for ``wordfreq.counter`` (stdlib ``unittest``)."""

import unittest

from wordfreq.counter import count_words, top


class CountWordsTests(unittest.TestCase):
    def test_counts_in_first_occurrence_order(self) -> None:
        self.assertEqual(count_words(["b", "a", "b"]), [("b", 2), ("a", 1)])

    def test_top_keeps_ties_in_order(self) -> None:
        self.assertEqual(top([("a", 1), ("b", 2), ("c", 1)], 2), [("b", 2), ("a", 1)])


if __name__ == "__main__":
    unittest.main()
