"""Tests for ``examboard`` (stdlib ``unittest``)."""

import unittest

from examboard.data import candidates, marks
from examboard.stats import exam_report

RESULTS = [(m, f"C{i}") for i, m in enumerate((55, 72, 90, 41, 72, 63, 18, 84, 77, 66))]


class ReportTests(unittest.TestCase):
    def test_report(self) -> None:
        self.assertEqual(
            exam_report(RESULTS),
            {
                "top": "C2 90",
                "median": "66",
                "upper quartile": "77",
                "boundaries": "84/72/63",
                "top decile mean": "90.00",
                "trimmed mean": "66.25",
                "widest gap": "23",
            },
        )

    def test_one_candidate(self) -> None:
        report = exam_report([(50, "C0")])
        self.assertEqual(report["top"], "C0 50")
        self.assertEqual(report["widest gap"], "0")


class DataTests(unittest.TestCase):
    def test_generation_is_deterministic(self) -> None:
        names = candidates(5)
        self.assertEqual(names, ["C00000", "C00001", "C00002", "C00003", "C00004"])
        self.assertEqual(marks(3, names), marks(3, names))
        self.assertNotEqual(marks(3, names), marks(4, names))
        self.assertTrue(all(0 <= mark <= 100 for mark, _ in marks(3, names)))


if __name__ == "__main__":
    unittest.main()
