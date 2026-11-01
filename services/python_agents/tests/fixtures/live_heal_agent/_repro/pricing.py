"""The report's scenario for pricing: three tins on 3-for-2 cost 3.98."""

import unittest

from pricing.cart import Cart


class ReportedCase(unittest.TestCase):
    def test_three_tins(self):
        cart = Cart()
        cart.add("1.99", 3, "3for2")
        cart.checkout("3.98")


if __name__ == "__main__":
    unittest.main()
