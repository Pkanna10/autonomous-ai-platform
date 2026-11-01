"""Tests for ``ledgerclose`` (stdlib ``unittest``)."""

import unittest

from ledgerclose.data import transfers
from ledgerclose.levels import level_numbers
from ledgerclose.report import money
from ledgerclose.settle import settle


class SettleTests(unittest.TestCase):
    def test_balances_and_running_total(self) -> None:
        balances, held = settle([(20, 500), (10, -200), (20, 100)])
        self.assertEqual(balances, {10: -200, 20: 600})
        self.assertEqual(list(balances), [10, 20])
        self.assertEqual(held, [500, 300, 400])

    def test_the_input_is_left_alone(self) -> None:
        pending = [(1, 1)]
        settle(pending)
        self.assertEqual(pending, [(1, 1)])
        self.assertEqual(settle([]), ({}, []))


class LevelTests(unittest.TestCase):
    def test_level_numbers(self) -> None:
        self.assertEqual(level_numbers([5, 12, 8, 31, 14, -3], 10), [1, 2, 1, 3, 2, 4])
        self.assertEqual(level_numbers([2, 1, 2], 1), [1, 2, 1])
        self.assertEqual(level_numbers([], 4), [])

    def test_step_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            level_numbers([1], 0)


class ReportTests(unittest.TestCase):
    def test_money(self) -> None:
        self.assertEqual(money(12345), "123.45")
        self.assertEqual(money(-5), "-0.05")
        self.assertEqual(money(0), "0.00")


class DataTests(unittest.TestCase):
    def test_generation_is_deterministic(self) -> None:
        self.assertEqual(transfers(20, 3), transfers(20, 3))

    def test_accounts_are_numbers_in_range(self) -> None:
        accounts = {account for account, _ in transfers(200, 7)}
        self.assertEqual(accounts, set(range(10000, 10007)))


if __name__ == "__main__":
    unittest.main()
