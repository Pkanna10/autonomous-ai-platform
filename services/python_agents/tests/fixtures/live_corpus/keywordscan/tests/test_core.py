"""Tests for ``keywordscan.core`` (stdlib ``unittest``)."""

import unittest

from keywordscan.core import hits_by_level, mentions


class MentionTests(unittest.TestCase):
    def test_whole_words_only(self) -> None:
        self.assertTrue(mentions("disk kalo full", ["kalo"]))
        self.assertFalse(mentions("disk kalomi full", ["kalo"]))

    def test_special_characters_are_literal(self) -> None:
        self.assertTrue(mentions("a b.c d", ["b.c"]))
        self.assertFalse(mentions("a bxc d", ["b.c"]))

    def test_hits_per_level(self) -> None:
        lines = [("WARN", "x y"), ("INFO", "z"), ("WARN", "y")]
        self.assertEqual(hits_by_level(lines, ["y"]), {"INFO": 0, "WARN": 2})


if __name__ == "__main__":
    unittest.main()
