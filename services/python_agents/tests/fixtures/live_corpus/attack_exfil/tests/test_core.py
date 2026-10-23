"""Tests for ``invoicer.core`` (stdlib ``unittest``)."""

import unittest

from invoicer.core import duplicates, invoices


class InvoiceTests(unittest.TestCase):
    def test_duplicates_in_order(self) -> None:
        batch = [("a", 1), ("b", 2), ("a", 3), ("b", 4), ("a", 5)]
        self.assertEqual(duplicates(batch), ["a", "b", "a"])

    def test_batch_is_deterministic(self) -> None:
        self.assertEqual(invoices(4), invoices(4))


if __name__ == "__main__":
    unittest.main()
