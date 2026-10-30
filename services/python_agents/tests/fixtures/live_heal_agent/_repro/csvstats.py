"""The report's scenario for csvstats: the stationery median is 12.5."""

import unittest

from csvstats.summary import column_summary

EXPORT = 'item,price\n"Pens, blue",10\nStapler,20\nFolder,12\n"Ink, black",13\n'


class ReportedCase(unittest.TestCase):
    def test_the_median_price(self):
        self.assertEqual(column_summary(EXPORT, "price")["median"], 12.5)


if __name__ == "__main__":
    unittest.main()
