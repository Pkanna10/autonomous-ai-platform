"""Tests for ``statementrun`` (stdlib ``unittest``)."""

import unittest

from statementrun.bank import Bank
from statementrun.data import transactions
from statementrun.layout import cells, money
from statementrun.printer import statement_lines

ROWS = [
    ("A-1", "03-01", "salary", 250000),
    ("A-2", "03-02", "rent", -95050),
    ("A-1", "03-04", "groceries", -4312),
]


class MoneyTests(unittest.TestCase):
    def test_money(self) -> None:
        self.assertEqual(money(123456789), "1,234,567.89")
        self.assertEqual(money(-5), "-0.05")
        self.assertEqual(money(0), "0.00")

    def test_cells(self) -> None:
        self.assertEqual(
            cells(("03-04", "fee", -150, 9850)), ("03-04", "fee", "-1.50", "98.50")
        )


class BankTests(unittest.TestCase):
    def test_statements_and_widths(self) -> None:
        bank = Bank(ROWS)
        self.assertEqual(bank.accounts(), ["A-1", "A-2"])
        self.assertEqual(
            bank.statement("A-1"),
            [
                ("03-01", "salary", 250000, 250000),
                ("03-04", "groceries", -4312, 245688),
            ],
        )
        self.assertEqual(bank.column_widths(), (5, 9, 8, 8))

    def test_printed_statement(self) -> None:
        self.assertEqual(
            statement_lines(Bank(ROWS), "A-2"),
            [
                "Statement A-2",
                "03-02  rent        -950.50   -950.50",
                "closing balance -950.50",
            ],
        )


class DataTests(unittest.TestCase):
    def test_generation_is_deterministic(self) -> None:
        self.assertEqual(transactions(30, 4), transactions(30, 4))
        self.assertEqual(
            {row[0] for row in transactions(30, 4)}, {"A-0", "A-1", "A-2", "A-3"}
        )


if __name__ == "__main__":
    unittest.main()
