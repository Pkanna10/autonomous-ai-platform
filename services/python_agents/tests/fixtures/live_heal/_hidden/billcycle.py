"""Hidden check for billcycle: December ends on the 31st; the rest still holds."""

import datetime as dt
import unittest

from billcycle.invoice import invoice_line
from billcycle.periods import billing_period, days_billed, month_end


class HiddenCheck(unittest.TestCase):
    def test_december_ends_on_the_31st(self):
        self.assertEqual(month_end(dt.date(2026, 12, 5)), dt.date(2026, 12, 31))

    def test_a_december_period(self):
        self.assertEqual(
            billing_period(dt.date(2025, 12, 31)),
            (dt.date(2025, 12, 1), dt.date(2025, 12, 31)),
        )
        self.assertEqual(days_billed(dt.date(2026, 12, 1)), 31)

    def test_a_december_invoice(self):
        line = invoice_line("acme", dt.date(2026, 12, 24), 49.0)
        self.assertEqual(line["period"], "2026-12-01..2026-12-31")

    def test_other_month_ends(self):
        self.assertEqual(month_end(dt.date(2028, 2, 10)), dt.date(2028, 2, 29))
        self.assertEqual(month_end(dt.date(2026, 11, 30)), dt.date(2026, 11, 30))
        self.assertEqual(month_end(dt.date(2027, 1, 31)), dt.date(2027, 1, 31))


if __name__ == "__main__":
    unittest.main()
