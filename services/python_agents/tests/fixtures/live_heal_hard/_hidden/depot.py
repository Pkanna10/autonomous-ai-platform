"""Hidden check for depot (a control): reserve takes the SKU first."""

import unittest

from depot.stock import Stock, UnknownSkuError


class HiddenCheck(unittest.TestCase):
    def test_a_quantity_where_the_sku_goes_is_an_unknown_sku(self):
        stock = Stock({"B-12": 40})
        with self.assertRaises(UnknownSkuError):
            stock.reserve(5, "B-12")
        self.assertEqual(stock.on_hand("B-12"), 40)

    def test_reserve_takes_the_sku_then_the_quantity(self):
        stock = Stock({"B-12": 40})
        self.assertEqual(stock.reserve("B-12", 5), 35)


if __name__ == "__main__":
    unittest.main()
