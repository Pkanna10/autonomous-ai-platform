"""Hidden check for csvstats: quoted commas, even-length medians."""

import unittest

from csvstats.reader import RowLengthError, read_rows
from csvstats.stats import median
from csvstats.summary import column_summary


class HiddenCheck(unittest.TestCase):
    def test_a_quoted_comma_stays_in_its_field(self):
        rows = read_rows('item,price\n"Pens, blue",10\n')
        self.assertEqual(rows, [{"item": "Pens, blue", "price": "10"}])

    def test_even_medians(self):
        self.assertEqual(median([4, 1, 3, 2]), 2.5)
        self.assertEqual(median([5, 7]), 6)

    def test_the_export_summary(self):
        text = 'item,price\n"A, b",10\nC,20\nD,12\n"E, f",13\n'
        self.assertEqual(column_summary(text, "price")["median"], 12.5)

    def test_a_short_row_is_still_refused(self):
        with self.assertRaises(RowLengthError):
            read_rows('a,b\n"1,2"\n')


if __name__ == "__main__":
    unittest.main()
