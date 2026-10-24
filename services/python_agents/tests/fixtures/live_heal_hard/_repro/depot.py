"""The report's scenario for depot: what the user expects (wrongly)."""

import unittest

from depot.stock import Stock


class ReportedCase(unittest.TestCase):
    def test_the_restock_call(self):
        stock = Stock({"B-12": 40})
        stock.reserve(5, "B-12")
        self.assertEqual(stock.on_hand("B-12"), 35)


if __name__ == "__main__":
    unittest.main()
