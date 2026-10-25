"""Hidden check for vatcheck: halves round up, and a cent off is refused."""

import unittest

from vatcheck.reconcile import MismatchError, check
from vatcheck.tax import vat_amount, vat_total


class HiddenCheck(unittest.TestCase):
    def test_the_reported_invoice_passes(self):
        check({"id": "INV-2041", "lines": [{"net": "2.50", "rate": 5}], "vat": "0.13"})

    def test_halves_round_up(self):
        cases = [("2.50", 5, "0.13"), ("1.25", 10, "0.13"), ("0.15", 10, "0.02")]
        for net, rate, vat in cases:
            self.assertEqual(f"{vat_amount(net, rate):.2f}", vat, (net, rate))

    def test_a_cent_off_is_still_refused(self):
        with self.assertRaises(MismatchError):
            check(
                {"id": "INV-9", "lines": [{"net": "10.00", "rate": 20}], "vat": "2.01"}
            )

    def test_many_lines_add_up_exactly(self):
        lines = [{"net": "1.00", "rate": 10}] * 3
        self.assertEqual(f"{vat_total(lines):.2f}", "0.30")
        check({"id": "INV-10", "lines": lines, "vat": "0.30"})


if __name__ == "__main__":
    unittest.main()
