import unittest

from chartscale.axis import axis_ticks, bar_heights, scale_factor


class AxisTest(unittest.TestCase):
    def test_scale_factor(self):
        self.assertEqual(scale_factor(50, 200), 4)

    def test_bar_heights(self):
        self.assertEqual(bar_heights([10, 25, 50], 200), [40, 100, 200])

    def test_axis_ticks(self):
        self.assertEqual(axis_ticks(50, 200), [0.0, 12.5, 25.0, 37.5, 50.0])

    def test_zero_max_is_refused(self):
        with self.assertRaises(ValueError):
            scale_factor(0, 200)


if __name__ == "__main__":
    unittest.main()
