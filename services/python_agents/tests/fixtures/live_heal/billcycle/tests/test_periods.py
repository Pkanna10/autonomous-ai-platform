import datetime as dt
import unittest

from billcycle.invoice import invoice_line
from billcycle.periods import billing_period, days_billed, month_end


class PeriodsTest(unittest.TestCase):
    def test_month_end_in_february(self):
        self.assertEqual(month_end(dt.date(2026, 2, 10)), dt.date(2026, 2, 28))

    def test_billing_period(self):
        self.assertEqual(
            billing_period(dt.date(2026, 4, 15)),
            (dt.date(2026, 4, 1), dt.date(2026, 4, 30)),
        )

    def test_days_billed(self):
        self.assertEqual(days_billed(dt.date(2026, 6, 1)), 30)

    def test_invoice_line(self):
        self.assertEqual(
            invoice_line("acme", dt.date(2026, 10, 24), 49.0),
            {
                "customer": "acme",
                "period": "2026-10-01..2026-10-31",
                "days": 31,
                "amount": 49.0,
            },
        )


if __name__ == "__main__":
    unittest.main()
