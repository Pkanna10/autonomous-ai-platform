"""Hidden check for confload: each file keeps its own delimiter."""

import unittest

from confload.cache import dialect_for, forget
from confload.loader import TableError, load_table

COLUMNS = ["sku", "price", "stock"]
US = "sku,price,stock\nA1,1.50,3\n"
EU = "sku;price;stock\nA1;1,50;3\n"


class HiddenCheck(unittest.TestCase):
    def setUp(self):
        forget()

    def test_eu_after_us(self):
        load_table("us_prices.csv", US, COLUMNS)
        self.assertEqual(load_table("eu_prices.csv", EU, COLUMNS)[1]["price"], "1,50")

    def test_each_file_has_its_own_delimiter(self):
        self.assertEqual(dialect_for("a.csv", "x,y\n"), ",")
        self.assertEqual(dialect_for("b.csv", "x;y\n"), ";")
        self.assertEqual(dialect_for("a.csv", "x;y\n"), ",")  # remembered

    def test_a_short_row_is_still_refused_after_another_file(self):
        load_table("us_prices.csv", US, COLUMNS)
        with self.assertRaises(TableError):
            load_table("eu_prices.csv", "sku;price;stock\nA1;1,50\n", COLUMNS)


if __name__ == "__main__":
    unittest.main()
