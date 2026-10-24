import unittest

from shipcost.checkout import quote, shipping_cost

ORDER = {
    "region": "eu-west",
    "lines": [
        {"price": 12.0, "qty": 2, "weight_kg": 0.5},
        {"price": 30.0, "qty": 1, "weight_kg": 1.5},
    ],
}


class CheckoutTest(unittest.TestCase):
    def test_shipping_cost(self):
        self.assertEqual(shipping_cost("us-east", 2.0), 9.4)

    def test_quote(self):
        self.assertEqual(
            quote(ORDER), {"subtotal": 54.0, "shipping": 6.5, "total": 60.5}
        )

    def test_weight_must_be_positive(self):
        with self.assertRaises(ValueError):
            shipping_cost("eu-west", 0)


if __name__ == "__main__":
    unittest.main()
