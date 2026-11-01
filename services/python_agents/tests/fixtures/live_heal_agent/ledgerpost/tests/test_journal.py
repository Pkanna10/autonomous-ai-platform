import unittest

from ledgerpost.journal import Entry, UnbalancedEntryError, post
from ledgerpost.ledger import Ledger
from ledgerpost.money import to_cents


class JournalTest(unittest.TestCase):
    def test_amounts(self):
        self.assertEqual(to_cents("12.30"), 1230)
        self.assertEqual(to_cents("7"), 700)
        with self.assertRaises(ValueError):
            to_cents("1.234")

    def test_a_balanced_entry_is_posted(self):
        ledger = Ledger()
        post(
            ledger,
            Entry(
                "d", "rent", (("rent", "debit", "900.00"), ("bank", "credit", "900.00"))
            ),
        )
        self.assertEqual(
            (ledger.balance("rent"), ledger.balance("bank")), (90000, -90000)
        )

    def test_an_unbalanced_entry_is_refused(self):
        with self.assertRaises(UnbalancedEntryError):
            post(
                Ledger(),
                Entry(
                    "d", "x", (("cash", "debit", "10.00"), ("sales", "credit", "9.99"))
                ),
            )


if __name__ == "__main__":
    unittest.main()
