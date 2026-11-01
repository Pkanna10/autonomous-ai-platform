import unittest

from csvstats.reader import RowLengthError, read_rows
from csvstats.stats import median
from csvstats.summary import column_summary

PRICES = "item,price\npen,2\nink,9\npad,4\n"


class SummaryTest(unittest.TestCase):
    def test_rows_are_read(self):
        self.assertEqual(read_rows("a,b\n1,2\n"), [{"a": "1", "b": "2"}])

    def test_an_odd_median(self):
        self.assertEqual(median([3, 1, 2]), 2)

    def test_a_column_summary(self):
        self.assertEqual(column_summary(PRICES, "price"), {"mean": 5.0, "median": 4.0})

    def test_a_short_row_is_refused(self):
        with self.assertRaises(RowLengthError):
            read_rows("a,b\n1\n")


if __name__ == "__main__":
    unittest.main()
