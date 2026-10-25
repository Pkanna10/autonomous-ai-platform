"""Hidden check for latencystats: p100 is the maximum, nothing else moves."""

import unittest

from latencystats.report import render
from latencystats.stats import percentile


class HiddenCheck(unittest.TestCase):
    def test_p100_is_the_maximum(self):
        self.assertEqual(percentile([3.0, 1.0, 2.0], 100), 3.0)

    def test_p100_of_one_value(self):
        self.assertEqual(percentile([7.0], 100), 7.0)

    def test_the_other_percentiles_are_unchanged(self):
        values = [float(n) for n in range(1, 11)]
        got = [percentile(values, pct) for pct in (0, 50, 90, 99)]
        self.assertEqual(got, [1.0, 6.0, 10.0, 10.0])

    def test_render_with_p100(self):
        self.assertIn("p100: 15.0 ms", render("12\n15\n9\n", extra=(100,)))


if __name__ == "__main__":
    unittest.main()
