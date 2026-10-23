"""Tests for ``distmatrix`` (stdlib ``unittest``)."""

import unittest

from distmatrix.distances import histogram, matrix, summaries
from distmatrix.points import generate


class DistanceTests(unittest.TestCase):
    def test_matrix_and_summaries(self) -> None:
        points = [(0.0, 0.0), (3.0, 4.0), (6.0, 8.0)]
        rows = matrix(points)
        self.assertEqual(rows[0], [0.0, 5.0, 10.0])
        self.assertEqual(summaries(rows), [(5.0, 7.5), (5.0, 5.0), (5.0, 7.5)])

    def test_histogram(self) -> None:
        self.assertEqual(histogram([0.5, 1.5, 9.0], 1.0, 3), [1, 1, 1])


class PointTests(unittest.TestCase):
    def test_points_are_deterministic(self) -> None:
        self.assertEqual(generate(20), generate(20))
        self.assertTrue(all(0 <= x < 1000 and 0 <= y < 1000 for x, y in generate(20)))


if __name__ == "__main__":
    unittest.main()
