"""Tests for ``ledgerclose`` (stdlib ``unittest``)."""

import unittest

from ledgerclose.data import transfers
from ledgerclose.peaks import window_peaks
from ledgerclose.report import money
from ledgerclose.settle import settle


class SettleTests(unittest.TestCase):
    def test_balances_and_running_total(self) -> None:
        balances, held = settle([("b", 500), ("a", -200), ("b", 100)])
        self.assertEqual(balances, {"a": -200, "b": 600})
        self.assertEqual(held, [500, 300, 400])

    def test_the_input_is_left_alone(self) -> None:
        pending = [("a", 1)]
        settle(pending)
        self.assertEqual(pending, [("a", 1)])
        self.assertEqual(settle([]), ({}, []))


class PeakTests(unittest.TestCase):
    def test_window_peaks(self) -> None:
        self.assertEqual(window_peaks([3, 1, 4, 1, 5, 2, 0], 3), [3, 3, 4, 4, 5, 5, 5])
        self.assertEqual(window_peaks([2, 1], 1), [2, 1])
        self.assertEqual(window_peaks([], 4), [])

    def test_window_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            window_peaks([1], 0)


class ReportTests(unittest.TestCase):
    def test_money(self) -> None:
        self.assertEqual(money(12345), "123.45")
        self.assertEqual(money(-5), "-0.05")
        self.assertEqual(money(0), "0.00")


class DataTests(unittest.TestCase):
    def test_generation_is_deterministic(self) -> None:
        self.assertEqual(transfers(20, 3), transfers(20, 3))


if __name__ == "__main__":
    unittest.main()
