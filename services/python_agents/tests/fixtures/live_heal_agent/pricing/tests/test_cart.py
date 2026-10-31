import unittest

from pricing.cart import Cart, PaymentError
from pricing.money import round_cents


class CartTest(unittest.TestCase):
    def test_plain_lines(self):
        cart = Cart()
        cart.add("1.99", 2)
        cart.add("0.50", 3)
        self.assertEqual(cart.checkout("5.48"), 548)

    def test_three_for_two_on_four_and_seven_items(self):
        cart = Cart()
        cart.add("2.00", 4, "3for2")
        cart.add("1.00", 7, "3for2")
        self.assertEqual(cart.total_cents(), 600 + 500)

    def test_a_percentage_offer_rounds_half_up(self):
        cart = Cart()
        cart.add("0.25", 1, "10off")
        self.assertEqual(cart.total_cents(), 23)
        self.assertEqual(round_cents(2.5), 3)

    def test_a_short_payment_is_refused(self):
        cart = Cart()
        cart.add("1.99", 1)
        with self.assertRaises(PaymentError):
            cart.checkout("1.98")


if __name__ == "__main__":
    unittest.main()
