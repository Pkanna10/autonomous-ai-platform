"""Tests for ``booklist`` (stdlib ``unittest``)."""

import unittest

from booklist.catalogue import Catalogue
from booklist.data import day
from booklist.links import slug
from booklist.shop import Shop


class CatalogueTests(unittest.TestCase):
    def test_ordered_titles(self) -> None:
        catalogue = Catalogue(["Pear", "Apple"])
        catalogue.add("Fig")
        catalogue.add("Apple")
        self.assertEqual(catalogue.ordered(), ["Apple", "Apple", "Fig", "Pear"])
        self.assertEqual(len(catalogue), 4)

    def test_the_starting_titles_are_left_alone(self) -> None:
        titles = ["b", "a"]
        Catalogue(titles).add("c")
        self.assertEqual(titles, ["b", "a"])


class ShopTests(unittest.TestCase):
    def test_listing_by_prefix(self) -> None:
        shop = Shop(Catalogue(["Bay Road", "Ash Lane", "Bat Cave", "Bee Hive"]), 2)
        self.assertEqual(shop.handle(("list", "Ba")), ["bat-cave", "bay-road"])
        self.assertIsNone(shop.handle(("add", "Bad Moon")))
        self.assertEqual(shop.handle(("list", "Ba")), ["bad-moon", "bat-cave"])
        self.assertEqual(shop.handle(("list", "Zz")), [])


class LinkTests(unittest.TestCase):
    def test_slug(self) -> None:
        self.assertEqual(slug("  The Rain, 2nd ed.  "), "the-rain-2nd-ed")
        self.assertEqual(slug("A--B"), "a-b")
        self.assertEqual(slug("!!"), "")


class DataTests(unittest.TestCase):
    def test_generation_is_deterministic(self) -> None:
        self.assertEqual(day(10, 20), day(10, 20))
        titles, commands = day(10, 20)
        self.assertEqual((len(titles), len(commands)), (10, 20))


if __name__ == "__main__":
    unittest.main()
