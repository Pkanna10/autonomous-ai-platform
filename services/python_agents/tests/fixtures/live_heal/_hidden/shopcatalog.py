"""Hidden check for shopcatalog: an unknown SKU raises ``UnknownProductError``."""

import unittest

from shopcatalog.lookup import UnknownProductError, find, in_stock, price_or_default

CATALOG = [
    {"sku": "A-100", "name": "Kettle", "price": 24.0},
    {"sku": "B-200", "name": "Teapot", "price": 18.5},
]


class HiddenCheck(unittest.TestCase):
    def test_an_unknown_sku_falls_back_to_the_default_price(self):
        self.assertEqual(price_or_default(CATALOG, "Z-404", 9.99), 9.99)

    def test_find_raises_unknown_product(self):
        with self.assertRaises(UnknownProductError):
            find(CATALOG, "Z-404")

    def test_in_stock_skips_unknown_skus(self):
        self.assertEqual(in_stock(CATALOG, ["Z-404", "A-100"]), ["A-100"])


if __name__ == "__main__":
    unittest.main()
