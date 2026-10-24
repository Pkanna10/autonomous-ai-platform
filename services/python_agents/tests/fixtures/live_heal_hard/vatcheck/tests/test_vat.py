import unittest

from vatcheck.reconcile import MismatchError, check
from vatcheck.tax import vat_amount

CLEAN = {
    "id": "INV-1",
    "lines": [{"net": "10.00", "rate": 20}, {"net": "40.00", "rate": 5}],
    "vat": "4.00",
}


class VatTest(unittest.TestCase):
    def test_vat_amount(self):
        self.assertEqual(f"{vat_amount('10.00', 20):.2f}", "2.00")
        self.assertEqual(f"{vat_amount('19.99', 0):.2f}", "0.00")

    def test_a_clean_invoice_passes(self):
        check(CLEAN)

    def test_a_wrong_invoice_is_refused(self):
        with self.assertRaises(MismatchError):
            check({**CLEAN, "vat": "5.00"})


if __name__ == "__main__":
    unittest.main()
