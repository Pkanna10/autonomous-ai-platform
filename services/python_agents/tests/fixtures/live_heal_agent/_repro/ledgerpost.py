"""The report's scenario for ledgerpost: the till sale posts."""

import unittest

from ledgerpost.journal import Entry, post
from ledgerpost.ledger import Ledger


class ReportedCase(unittest.TestCase):
    def test_the_till_sale(self):
        lines = (("cash", "debit", "100.5"), ("sales", "credit", "100.50"))
        post(Ledger(), Entry("2026-04-02", "till", lines))


if __name__ == "__main__":
    unittest.main()
