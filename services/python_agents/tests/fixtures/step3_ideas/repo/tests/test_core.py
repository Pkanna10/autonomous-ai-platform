"""Tests for ``dedupe`` (stdlib ``unittest``, so a trial needs no pytest).

Run with ``python -m unittest discover -s tests -t .`` from the project root.

The suite pins set semantics and the order of input that is already
ascending. It deliberately does not pin first-occurrence order on unsorted
input: a rewrite that sorts the result passes it, and only an output
comparison of the workload catches that change. Likewise the histogram is
pinned on input without repeats only, so counting the distinct values instead
of every item passes it.
"""

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

from dedupe.core import (
    bucket_bounds,
    contains,
    running_totals,
    summarise,
    unique_in_order,
)
from dedupe.main import build_input, main


class ContainsTests(unittest.TestCase):
    def test_finds_a_present_value(self) -> None:
        self.assertTrue(contains([4, 1, 7], 7))

    def test_misses_an_absent_value(self) -> None:
        self.assertFalse(contains([4, 1, 7], 5))

    def test_empty_values_hold_nothing(self) -> None:
        self.assertFalse(contains([], 0))


class UniqueInOrderTests(unittest.TestCase):
    def test_empty_input_gives_empty_list(self) -> None:
        self.assertEqual(unique_in_order([]), [])

    def test_removes_duplicates(self) -> None:
        result = unique_in_order([3, 1, 3, 2, 1, 2])
        self.assertEqual(sorted(result), [1, 2, 3])

    def test_keeps_the_order_of_ascending_input(self) -> None:
        self.assertEqual(unique_in_order([1, 1, 2, 3, 3, 3, 5]), [1, 2, 3, 5])

    def test_accepts_any_iterable(self) -> None:
        result = unique_in_order(i % 4 for i in range(20))
        self.assertEqual(sorted(result), [0, 1, 2, 3])

    def test_returns_a_list(self) -> None:
        self.assertIsInstance(unique_in_order((2, 2, 1)), list)

    def test_generated_input_keeps_each_value_once(self) -> None:
        items = build_input(2_000)
        result = unique_in_order(items)
        self.assertEqual(len(result), len(set(result)))
        self.assertEqual(set(result), set(items))


class RunningTotalsTests(unittest.TestCase):
    def test_empty_input_gives_empty_list(self) -> None:
        self.assertEqual(running_totals([]), [])

    def test_sums_each_prefix(self) -> None:
        self.assertEqual(running_totals([1, 2, 3, 4]), [1, 3, 6, 10])

    def test_last_total_is_the_sum(self) -> None:
        values = build_input(500)
        self.assertEqual(running_totals(values)[-1], sum(values))


class BucketTests(unittest.TestCase):
    def test_bounds_split_the_range_evenly(self) -> None:
        self.assertEqual(bucket_bounds(10, 4), [0, 2, 5, 7, 10])

    def test_counts_fill_the_buckets_of_distinct_input(self) -> None:
        _, _, counts = summarise([9, 0, 4, 2, 7, 1, 5, 3, 8, 6], 4)
        self.assertEqual(counts, [2, 3, 2, 3])

    def test_summarise_returns_the_three_results(self) -> None:
        unique, totals, counts = summarise([0, 1, 2, 3], 2)
        self.assertEqual((unique, totals, counts), ([0, 1, 2, 3], [0, 1, 3, 6], [2, 2]))


class BuildInputTests(unittest.TestCase):
    def test_is_deterministic(self) -> None:
        # Known answers pin the generator: a change to the seed handling or the
        # LCG constants changes every stdout fingerprint the E2E relies on.
        self.assertEqual(build_input(10), [3, 0, 2, 2, 5, 1, 5, 7, 8, 3])
        self.assertEqual(build_input(10, seed=7), [8, 1, 3, 3, 5, 9, 4, 4, 9, 6])

    def test_values_lie_in_range(self) -> None:
        values = build_input(300)
        self.assertEqual(len(values), 300)
        self.assertTrue(all(0 <= value < 300 for value in values))

    def test_has_duplicates_to_remove(self) -> None:
        values = build_input(1_000)
        self.assertLess(len(set(values)), len(values))


class MainTests(unittest.TestCase):
    def run_main(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_prints_a_stable_digest(self) -> None:
        code, first, _ = self.run_main(["400"])
        _, second, _ = self.run_main(["400"])
        self.assertEqual(code, 0)
        self.assertEqual(first, second)
        keys = [line.split("=", 1)[0] for line in first.splitlines()]
        self.assertEqual(
            keys, ["items", "unique", "head", "tail", "totals", "buckets", "sha256"]
        )
        self.assertIn("items=400\n", first)

    def test_rejects_a_bad_count(self) -> None:
        for argv in (["0"], ["-3"], ["many"], ["1", "2"]):
            with self.subTest(argv=argv):
                code, out, err = self.run_main(argv)
                self.assertEqual(code, 2)
                self.assertEqual(out, "")
                self.assertIn("usage:", err)


if __name__ == "__main__":
    unittest.main()
