import unittest

from invoicer.lines import Line, parse_line
from invoicer.tax import TaxRateError
from invoicer.totals import invoice_total


class TotalsTest(unittest.TestCase):
    def test_food_pays_the_reduced_rate(self):
        self.assertEqual(invoice_total([Line("FD-7", 3, 200)], "de"), 642)

    def test_standard_items_and_an_unknown_prefix(self):
        lines = [Line("EL-9", 1, 10000), Line("ZZ-1", 1, 100)]
        self.assertEqual(invoice_total(lines, "de"), 11900 + 119)

    def test_an_unknown_country_is_refused(self):
        with self.assertRaises(TaxRateError):
            invoice_total([Line("FD-7", 1, 200)], "xx")

    def test_a_line_is_parsed(self):
        self.assertEqual(
            parse_line("2 x BK-1001 @ 10.00 - 2.00"), Line("BK-1001", 2, 1000, 200)
        )


if __name__ == "__main__":
    unittest.main()
