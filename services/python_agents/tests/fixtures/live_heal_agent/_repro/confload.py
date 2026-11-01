"""The report's scenario for confload: eu_prices.csv after us_prices.csv."""

import unittest

from confload.loader import load_table

COLUMNS = ["sku", "price", "stock"]


class ReportedCase(unittest.TestCase):
    def test_the_nightly_order(self):
        load_table("us_prices.csv", "sku,price,stock\nA1,1.50,3\n", COLUMNS)
        load_table("eu_prices.csv", "sku;price;stock\nA1;1,50;3\n", COLUMNS)


if __name__ == "__main__":
    unittest.main()
