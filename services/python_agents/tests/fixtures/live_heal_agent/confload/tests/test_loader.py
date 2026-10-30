import unittest

from confload.cache import forget
from confload.loader import TableError, load_table
from confload.sniff import sniff

COLUMNS = ["sku", "price", "stock"]


class LoaderTest(unittest.TestCase):
    def setUp(self):
        forget()

    def test_a_comma_table(self):
        rows = load_table("us.csv", "sku,price,stock\nA1,1.50,3\n", COLUMNS)
        self.assertEqual(rows[1], {"sku": "A1", "price": "1.50", "stock": "3"})

    def test_a_semicolon_table(self):
        rows = load_table("eu.csv", "sku;price;stock\nA1;1,50;3\n", COLUMNS)
        self.assertEqual(rows[1]["price"], "1,50")

    def test_sniffing(self):
        self.assertEqual(sniff("a|b|c\n"), "|")
        self.assertEqual(sniff("abc\n"), ",")

    def test_a_short_row_is_refused(self):
        with self.assertRaises(TableError):
            load_table("x.csv", "sku,price,stock\nA1,1.50\n", COLUMNS)


if __name__ == "__main__":
    unittest.main()
