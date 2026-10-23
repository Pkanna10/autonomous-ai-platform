"""Tests for ``shipmerge`` (stdlib ``unittest``)."""

import unittest

from shipmerge.catalog import distinct_skus, units_by_warehouse
from shipmerge.data import Shipment, shipments
from shipmerge.orders import arrival_ranks, order_numbers, rank_digest


def _line(warehouse: str, order_id: int, sku: str, quantity: int = 1) -> Shipment:
    return Shipment(warehouse, order_id, sku, quantity)


class CatalogTests(unittest.TestCase):
    def test_distinct_skus_keep_first_appearance_order(self) -> None:
        lines = [_line("n", 1, "B"), _line("s", 2, "A"), _line("n", 3, "B")]
        self.assertEqual(distinct_skus(lines), ["B", "A"])
        self.assertEqual(distinct_skus([]), [])

    def test_units_by_warehouse(self) -> None:
        lines = [_line("s", 1, "A", 2), _line("n", 1, "A", 3), _line("s", 2, "B", 4)]
        self.assertEqual(units_by_warehouse(lines), {"n": 3, "s": 6})


class OrderTests(unittest.TestCase):
    def test_ranks_follow_ascending_order_numbers(self) -> None:
        lines = [_line("n", 30, "A"), _line("n", 10, "A"), _line("s", 30, "B")]
        self.assertEqual(order_numbers(lines), [10, 30])
        self.assertEqual(arrival_ranks(lines), [1, 0, 1])

    def test_digest_depends_on_position(self) -> None:
        self.assertNotEqual(rank_digest([1, 2]), rank_digest([2, 1]))
        self.assertEqual(rank_digest([]), 0)


class DataTests(unittest.TestCase):
    def test_generation_is_deterministic(self) -> None:
        self.assertEqual(shipments(50, 10, 5), shipments(50, 10, 5))
        self.assertTrue(all(1 <= s.quantity <= 12 for s in shipments(50, 10, 5)))


if __name__ == "__main__":
    unittest.main()
