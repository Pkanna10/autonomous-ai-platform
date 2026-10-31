"""Hidden check for splitbill: shares add up and differ by one cent at most."""

import unittest

from splitbill.bill import Bill
from splitbill.split import split_evenly


class HiddenCheck(unittest.TestCase):
    def test_three_friends(self):
        self.assertEqual(
            Bill(["10.00"]).settle(["ana", "ben", "cy"]),
            {"ana": "3.34", "ben": "3.33", "cy": "3.33"},
        )

    def test_shares_differ_by_one_cent_at_most(self):
        for total, people in ((100, 7), (1000, 6), (1001, 3), (5, 4)):
            shares = split_evenly(total, people)
            self.assertEqual(sum(shares), total)
            self.assertLessEqual(max(shares) - min(shares), 1, shares)
            self.assertEqual(shares, sorted(shares, reverse=True))


if __name__ == "__main__":
    unittest.main()
