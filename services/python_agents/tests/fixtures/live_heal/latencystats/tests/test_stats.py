import unittest

from latencystats.report import parse_samples, render
from latencystats.stats import percentile, summary

TEN = [float(n) for n in range(10, 0, -1)]


class PercentileTest(unittest.TestCase):
    def test_median_of_ten(self):
        self.assertEqual(percentile(TEN, 50), 6.0)

    def test_p90_of_ten(self):
        self.assertEqual(percentile(TEN, 90), 10.0)

    def test_no_values_are_refused(self):
        with self.assertRaises(ValueError):
            percentile([], 50)

    def test_summary(self):
        self.assertEqual(summary(TEN), {"p50": 6.0, "p90": 10.0, "p99": 10.0})


class ReportTest(unittest.TestCase):
    def test_comments_and_blank_lines_are_skipped(self):
        self.assertEqual(parse_samples("12\n\n# warm-up\n9.5\n"), [12.0, 9.5])

    def test_render(self):
        self.assertEqual(
            render("12\n15\n9\n"), "p50: 12.0 ms\np90: 15.0 ms\np99: 15.0 ms"
        )


if __name__ == "__main__":
    unittest.main()
