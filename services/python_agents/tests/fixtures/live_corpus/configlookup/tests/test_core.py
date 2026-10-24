"""Tests for ``configlookup.core`` (stdlib ``unittest``)."""

import unittest

from configlookup.core import price, rule_for, totals


class PricingTests(unittest.TestCase):
    def test_rule(self) -> None:
        self.assertEqual(
            rule_for("cat-001"), {"discount_permille": 11, "tax_permille": 87}
        )

    def test_price_discount_then_tax(self) -> None:
        self.assertEqual(price("cat-001", 1000), 1075)
        self.assertEqual(price("cat-000", 1000), 1050)

    def test_unknown_category(self) -> None:
        with self.assertRaises(KeyError):
            price("nope", 1)

    def test_totals_by_group(self) -> None:
        self.assertEqual(
            totals([("cat-001", 1000), ("cat-000", 1000), ("cat-150", 0)]),
            {"cat-0": 2125, "cat-1": 0},
        )


if __name__ == "__main__":
    unittest.main()
