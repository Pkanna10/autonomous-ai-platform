"""Tests for ``slowsum`` (stdlib ``unittest``).

Run with ``python -m unittest discover -s tests -t .`` from the project root.
"""

import unittest

from slowsum.core import common_count
from slowsum.main import values


class CommonCountTests(unittest.TestCase):
    def test_counts_repeats_on_the_left(self) -> None:
        self.assertEqual(common_count([1, 1, 2, 9], [1, 2, 3]), 3)

    def test_empty_lists(self) -> None:
        self.assertEqual(common_count([], [1]), 0)
        self.assertEqual(common_count([1], []), 0)

    def test_workload_input_is_deterministic(self) -> None:
        self.assertEqual(values(5, 1), values(5, 1))


if __name__ == "__main__":
    unittest.main()
