"""Tests for ``tokenparse.core`` (stdlib ``unittest``)."""

import unittest

from tokenparse.core import tally


class TallyTests(unittest.TestCase):
    def test_words_and_integers(self) -> None:
        self.assertEqual(tally("abc 12 -5 x 0"), (2, 3, 7))

    def test_empty(self) -> None:
        self.assertEqual(tally(""), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
