"""The report's scenario for stockbook: 500 g out of 2 kg books."""

import unittest

from stockbook.ledger import Ledger


class ReportedCase(unittest.TestCase):
    def test_issuing_grams(self):
        ledger = Ledger()
        ledger.receive("flour", 2)
        ledger.issue("flour", 500, "g")


if __name__ == "__main__":
    unittest.main()
