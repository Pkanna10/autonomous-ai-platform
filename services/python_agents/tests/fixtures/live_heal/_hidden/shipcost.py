"""Hidden check for shipcost: a region without a rate card pays the default."""

import unittest

from shipcost.checkout import quote, shipping_cost
from shipcost.rates import DEFAULT_RATE, rate_for


class HiddenCheck(unittest.TestCase):
    def test_an_unknown_region_gets_the_default_rate(self):
        self.assertEqual(rate_for("eu-north"), DEFAULT_RATE)

    def test_shipping_to_an_unknown_region(self):
        self.assertEqual(shipping_cost("eu-north", 2.0), 13.5)

    def test_a_quote_for_an_unknown_region(self):
        order = {
            "region": "ap-south",
            "lines": [{"price": 10.0, "qty": 1, "weight_kg": 1.0}],
        }
        self.assertEqual(
            quote(order), {"subtotal": 10.0, "shipping": 11.5, "total": 21.5}
        )

    def test_known_regions_keep_their_rates(self):
        self.assertEqual(shipping_cost("eu-central", 1.0), 5.9)


if __name__ == "__main__":
    unittest.main()
