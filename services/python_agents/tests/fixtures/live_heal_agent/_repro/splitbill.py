"""The report's scenario for splitbill: 10.00 among three friends."""

import unittest

from splitbill.bill import Bill


class ReportedCase(unittest.TestCase):
    def test_three_friends(self):
        shares = Bill(["10.00"]).settle(["ana", "ben", "cy"])
        self.assertEqual(shares, {"ana": "3.34", "ben": "3.33", "cy": "3.33"})


if __name__ == "__main__":
    unittest.main()
