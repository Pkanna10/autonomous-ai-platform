"""Hidden check for pricing: every third item free, rounding unchanged."""

import unittest

from pricing.cart import Cart
from pricing.money import round_cents
from pricing.offers import free_items


class HiddenCheck(unittest.TestCase):
    def test_three_tins(self):
        cart = Cart()
        cart.add("1.99", 3, "3for2")
        self.assertEqual(cart.checkout("3.98"), 398)

    def test_every_third_item_is_free(self):
        counts = [free_items("3for2", n) for n in range(10)]
        self.assertEqual(counts, [0, 0, 0, 1, 1, 1, 2, 2, 2, 3])

    def test_rounding_stays_half_up(self):
        self.assertEqual([round_cents(x) for x in (0.5, 1.5, 2.5, 2.4)], [1, 2, 3, 2])

    def test_a_six_pack(self):
        cart = Cart()
        cart.add("0.99", 6, "3for2")
        self.assertEqual(cart.checkout("3.96"), 396)


if __name__ == "__main__":
    unittest.main()
