import unittest

from depot.orders import reserve_order
from depot.stock import OutOfStockError, Stock, UnknownSkuError


class StockTest(unittest.TestCase):
    def test_reserve(self):
        stock = Stock({"B-12": 40})
        self.assertEqual(stock.reserve("B-12", 5), 35)
        self.assertEqual(stock.on_hand("B-12"), 35)

    def test_too_many(self):
        with self.assertRaises(OutOfStockError):
            Stock({"B-12": 4}).reserve("B-12", 5)

    def test_unknown(self):
        with self.assertRaises(UnknownSkuError):
            Stock({"B-12": 4}).reserve("Z-1", 1)

    def test_order(self):
        order = {"lines": [{"sku": "B-12", "qty": 2}, {"sku": "N-3", "qty": 1}]}
        self.assertEqual(
            reserve_order(Stock({"B-12": 4, "N-3": 9}), order), {"B-12": 2, "N-3": 8}
        )


if __name__ == "__main__":
    unittest.main()
