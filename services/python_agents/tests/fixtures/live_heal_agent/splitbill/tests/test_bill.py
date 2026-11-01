import unittest

from splitbill.bill import Bill
from splitbill.split import split_evenly


class BillTest(unittest.TestCase):
    def test_an_even_split(self):
        self.assertEqual(split_evenly(900, 3), [300, 300, 300])

    def test_a_bill_with_a_tip(self):
        bill = Bill(["40.00", "20.00"], tip_percent=10)
        self.assertEqual(bill.total_cents(), 6600)
        self.assertEqual(bill.settle(["ana", "ben"]), {"ana": "33.00", "ben": "33.00"})

    def test_four_people(self):
        self.assertEqual(split_evenly(1000, 4), [250] * 4)


if __name__ == "__main__":
    unittest.main()
