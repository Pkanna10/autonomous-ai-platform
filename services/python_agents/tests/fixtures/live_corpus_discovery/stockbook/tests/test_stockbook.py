"""Tests for ``stockbook`` (stdlib ``unittest``)."""

import unittest

from stockbook.book import Book
from stockbook.checks import line_digest
from stockbook.data import movements
from stockbook.registry import Registry


class RegistryTests(unittest.TestCase):
    def test_rows_follow_first_appearance(self) -> None:
        registry = Registry()
        self.assertEqual([registry.row(c) for c in "baba"], [0, 1, 0, 1])
        self.assertEqual(registry.row("c"), 2)
        self.assertEqual(registry.codes(), ["b", "a", "c"])

    def test_codes_is_a_copy(self) -> None:
        registry = Registry()
        registry.row("x")
        registry.codes().append("y")
        self.assertEqual(registry.codes(), ["x"])


class BookTests(unittest.TestCase):
    def test_levels_and_backorders(self) -> None:
        book = Book()
        for line in ("R|b|5", "S|a|3", "S|b|7", "R|a|4", "S|a|1"):
            book.apply(line)
        self.assertEqual(book.levels(), {"b": 0, "a": 3})
        self.assertEqual(book.shortfall, 5)


class CheckTests(unittest.TestCase):
    def test_line_digest(self) -> None:
        self.assertEqual(line_digest(""), 7)
        self.assertEqual(line_digest("A"), 7 * 131 + 65)
        self.assertNotEqual(line_digest("R|a|1"), line_digest("R|a|2"))


class DataTests(unittest.TestCase):
    def test_generation_is_deterministic(self) -> None:
        lines = movements(30, 4)
        self.assertEqual(lines, movements(30, 4))
        self.assertTrue(all(line[0] in "RS" and line.count("|") == 2 for line in lines))


if __name__ == "__main__":
    unittest.main()
