import unittest

from stockbook.ledger import Ledger, LedgerError
from stockbook.units import to_kg


class LedgerTest(unittest.TestCase):
    def test_receive_and_issue(self):
        ledger = Ledger()
        ledger.receive("flour", 25)
        ledger.issue("flour", 2.5)
        self.assertAlmostEqual(ledger.stock("flour"), 22.5)

    def test_issuing_more_than_the_stock_is_refused(self):
        ledger = Ledger()
        ledger.receive("salt", 1)
        with self.assertRaises(LedgerError):
            ledger.issue("salt", 2)
        self.assertEqual(ledger.stock("salt"), 1)

    def test_kilograms_are_kilograms(self):
        self.assertEqual(to_kg(3, "kg"), 3)


if __name__ == "__main__":
    unittest.main()
