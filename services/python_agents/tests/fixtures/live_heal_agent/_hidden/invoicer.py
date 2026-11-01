"""Hidden check for invoicer: any case of country code, tax after discount."""

import unittest

from invoicer.lines import Line
from invoicer.tax import TaxRateError
from invoicer.totals import invoice_total


class HiddenCheck(unittest.TestCase):
    def test_an_upper_case_country_code(self):
        self.assertEqual(invoice_total([Line("BK-1001", 2, 1000, 200)], "DE"), 1926)

    def test_tax_is_paid_on_the_discounted_amount(self):
        self.assertEqual(invoice_total([Line("EL-7", 1, 10000, 1000)], "fr"), 10800)

    def test_mixed_case_and_several_lines(self):
        lines = [Line("FD-1", 4, 250, 100), Line("EL-2", 1, 5000)]
        self.assertEqual(invoice_total(lines, "De"), 900 + 63 + 5000 + 950)

    def test_an_unknown_country_is_still_refused(self):
        with self.assertRaises(TaxRateError):
            invoice_total([Line("BK-1", 1, 100)], "XX")


if __name__ == "__main__":
    unittest.main()
