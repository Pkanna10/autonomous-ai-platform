"""Tests for ``lettertally.core`` (stdlib ``unittest``)."""

import unittest

from lettertally.core import VOCABULARY, sample, top_words


class TallyTests(unittest.TestCase):
    def test_vocabulary(self) -> None:
        self.assertEqual(len(VOCABULARY), 84)

    def test_sample_is_seeded(self) -> None:
        self.assertEqual(sample(10), sample(10))

    def test_top_words(self) -> None:
        self.assertEqual(
            top_words(["a", "b", "b", "c", "a", "b"], 2), [("b", 3), ("a", 2)]
        )


if __name__ == "__main__":
    unittest.main()
