"""The report's scenario for invoicer: the German invoice totals 19.26."""

import unittest

from invoicer.lines import parse_line
from invoicer.totals import invoice_total


class ReportedCase(unittest.TestCase):
    def test_the_german_book_invoice(self):
        lines = [parse_line("2 x BK-1001 @ 10.00 - 2.00")]
        self.assertEqual(invoice_total(lines, "DE"), 1926)


if __name__ == "__main__":
    unittest.main()
