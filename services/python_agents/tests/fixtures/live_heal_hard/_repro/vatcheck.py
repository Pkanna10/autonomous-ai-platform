"""The report's scenario for vatcheck: INV-2041 is accepted."""

import unittest

from vatcheck.reconcile import check


class ReportedCase(unittest.TestCase):
    def test_inv_2041_is_accepted(self):
        check({"id": "INV-2041", "lines": [{"net": "2.50", "rate": 5}], "vat": "0.13"})


if __name__ == "__main__":
    unittest.main()
