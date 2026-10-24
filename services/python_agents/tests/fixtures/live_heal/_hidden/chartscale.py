"""Hidden check for chartscale: the scale is exact, whatever the values."""

import unittest

from chartscale.axis import axis_ticks, bar_heights, scale_factor


class HiddenCheck(unittest.TestCase):
    def test_axis_for_values_above_the_height(self):
        self.assertEqual(axis_ticks(500, 200), [0.0, 125.0, 250.0, 375.0, 500.0])

    def test_the_largest_bar_fills_the_chart(self):
        self.assertEqual(bar_heights([30, 15], 200), [200, 100])

    def test_the_scale_factor_is_exact(self):
        self.assertAlmostEqual(scale_factor(500, 200), 0.4)
        self.assertAlmostEqual(scale_factor(30, 200), 200 / 30)


if __name__ == "__main__":
    unittest.main()
