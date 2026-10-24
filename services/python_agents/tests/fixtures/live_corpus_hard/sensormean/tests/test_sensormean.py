"""Tests for ``sensormean`` (stdlib ``unittest``)."""

import unittest

from sensormean.readings import series
from sensormean.stats import running_extremes, running_means


class StatsTests(unittest.TestCase):
    def test_running_means(self) -> None:
        means = running_means([1.0, 2.0, 6.0])
        self.assertEqual(len(means), 3)
        for got, want in zip(means, [1.0, 1.5, 3.0], strict=True):
            self.assertAlmostEqual(got, want, places=9)
        self.assertEqual(running_means([]), [])

    def test_means_of_a_generated_series(self) -> None:
        values = series(1, 300)
        means = running_means(values)
        self.assertAlmostEqual(means[-1], sum(values) / len(values), places=9)

    def test_running_extremes(self) -> None:
        self.assertEqual(
            running_extremes([3.0, 1.0, 4.0]), [(3.0, 3.0), (1.0, 3.0), (1.0, 4.0)]
        )


class ReadingTests(unittest.TestCase):
    def test_series_is_deterministic(self) -> None:
        self.assertEqual(series(2, 50), series(2, 50))


if __name__ == "__main__":
    unittest.main()
