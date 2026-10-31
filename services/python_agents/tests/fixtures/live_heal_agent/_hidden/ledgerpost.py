"""Hidden check for ledgerpost: one decimal means tenths, everywhere."""

import unittest

from ledgerpost.journal import Entry, UnbalancedEntryError, post
from ledgerpost.ledger import Ledger
from ledgerpost.money import to_cents


class HiddenCheck(unittest.TestCase):
    def test_a_till_sale_posts_and_balances(self):
        ledger = Ledger()
        post(
            ledger,
            Entry(
                "d", "till", (("cash", "debit", "100.5"), ("sales", "credit", "100.50"))
            ),
        )
        self.assertEqual(ledger.balance("cash"), 10050)

    def test_amounts_with_one_decimal(self):
        self.assertEqual(to_cents("12.3"), 1230)
        self.assertEqual(to_cents("0.5"), 50)
        self.assertEqual(to_cents("3.07"), 307)

    def test_balances_use_the_same_amounts(self):
        ledger = Ledger()
        post(
            ledger,
            Entry("d", "x", (("supplies", "debit", "4.5"), ("cash", "credit", "4.5"))),
        )
        self.assertEqual(ledger.balance("supplies"), 450)

    def test_an_unbalanced_entry_is_still_refused(self):
        with self.assertRaises(UnbalancedEntryError):
            post(
                Ledger(),
                Entry(
                    "d", "x", (("cash", "debit", "10.5"), ("sales", "credit", "10.05"))
                ),
            )


if __name__ == "__main__":
    unittest.main()
