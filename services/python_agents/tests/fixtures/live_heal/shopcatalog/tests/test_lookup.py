import unittest

from shopcatalog.lookup import find, in_stock, price_or_default

CATALOG = [
    {"sku": "A-100", "name": "Kettle", "price": 24.0},
    {"sku": "B-200", "name": "Teapot", "price": 18.5},
]


class LookupTest(unittest.TestCase):
    def test_find(self):
        self.assertEqual(find(CATALOG, "B-200")["name"], "Teapot")

    def test_price_of_a_stocked_product(self):
        self.assertEqual(price_or_default(CATALOG, "A-100", 0.0), 24.0)

    def test_in_stock_keeps_the_order(self):
        self.assertEqual(in_stock(CATALOG, ["B-200", "A-100"]), ["B-200", "A-100"])


if __name__ == "__main__":
    unittest.main()
