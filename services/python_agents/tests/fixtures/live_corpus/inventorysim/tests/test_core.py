"""Tests for ``inventorysim.core`` (stdlib ``unittest``)."""

import unittest

from inventorysim.core import make_warehouse, run_day, simulate, stock_value


class SimulationTests(unittest.TestCase):
    def test_value(self) -> None:
        self.assertEqual(stock_value({"a": {"stock": [2, 1], "price": [5, 7]}}), 17)

    def test_audit_is_taken_before_each_day(self) -> None:
        warehouse = make_warehouse(3, 4)
        start = stock_value(warehouse)
        audit = simulate(warehouse, 3)
        self.assertEqual(audit[0], start)
        self.assertEqual(len(audit), 3)

    def test_simulate_mutates_like_run_day(self) -> None:
        left, right = make_warehouse(4, 5), make_warehouse(4, 5)
        simulate(left, 6)
        for day in range(6):
            run_day(right, day)
        self.assertEqual(left, right)


if __name__ == "__main__":
    unittest.main()
