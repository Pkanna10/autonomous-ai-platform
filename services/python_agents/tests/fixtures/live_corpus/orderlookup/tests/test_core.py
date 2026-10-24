"""Tests for ``orderlookup.core`` (stdlib ``unittest``)."""

import unittest

from orderlookup.core import find_customer, totals_by_region
from orderlookup.data import Customer, Order


class JoinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.people = [Customer(7, "a", "emea"), Customer(3, "b", "apac")]

    def test_find(self) -> None:
        self.assertEqual(find_customer(self.people, 3).name, "b")
        with self.assertRaises(KeyError):
            find_customer(self.people, 4)

    def test_totals(self) -> None:
        orders = [Order(1, 7, 10), Order(2, 3, 5), Order(3, 7, 1)]
        self.assertEqual(totals_by_region(orders, self.people), {"apac": 5, "emea": 11})

    def test_unknown_customer_fails(self) -> None:
        with self.assertRaises(KeyError):
            totals_by_region([Order(1, 99, 1)], self.people)


if __name__ == "__main__":
    unittest.main()
