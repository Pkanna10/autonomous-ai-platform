"""Hidden check for stockbook: every unit converts to kilograms."""

import unittest

from stockbook.ledger import Ledger, LedgerError
from stockbook.units import to_kg


class HiddenCheck(unittest.TestCase):
    def test_the_reported_issue_books(self):
        ledger = Ledger()
        ledger.receive("flour", 2)
        ledger.issue("flour", 500, "g")
        self.assertAlmostEqual(ledger.stock("flour"), 1.5)

    def test_units(self):
        self.assertAlmostEqual(to_kg(500, "g"), 0.5)
        self.assertAlmostEqual(to_kg(250, "mg"), 0.00025)
        self.assertAlmostEqual(to_kg(2, "t"), 2000)

    def test_receiving_grams(self):
        ledger = Ledger()
        ledger.receive("yeast", 250, "g")
        self.assertAlmostEqual(ledger.stock("yeast"), 0.25)
        with self.assertRaises(LedgerError):
            ledger.issue("yeast", 300, "g")


if __name__ == "__main__":
    unittest.main()
