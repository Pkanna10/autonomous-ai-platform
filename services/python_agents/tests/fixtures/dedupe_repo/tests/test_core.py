"""Tests for ``dedupe`` (stdlib ``unittest``, so a trial needs no pytest).

Run with ``python -m unittest discover -s tests -t .`` from the project root.

The suite pins set semantics and the order of input that is already
ascending. It deliberately does not pin first-occurrence order on unsorted
input: a rewrite that sorts the result passes it, and only an output
comparison of the workload catches that change.
"""

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

from dedupe.core import unique_in_order
from dedupe.main import build_input, main


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
        self.assertEqual(keys, ["items", "unique", "head", "tail", "sha256"])
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
