"""Tests for ``wordcount.core`` (stdlib ``unittest``)."""

import unittest

from wordcount.core import frequencies, most_common


class FrequencyTests(unittest.TestCase):
    def test_counts_sorted_by_word(self) -> None:
        freq = frequencies(["b", "a", "b", "c", "b", "a"])
        self.assertEqual(freq, {"a": 2, "b": 3, "c": 1})
        self.assertEqual(list(freq), ["a", "b", "c"])

    def test_most_common_ties_alphabetical(self) -> None:
        self.assertEqual(most_common({"b": 2, "a": 2, "c": 5}, 2), [("c", 5), ("a", 2)])


if __name__ == "__main__":
    unittest.main()
