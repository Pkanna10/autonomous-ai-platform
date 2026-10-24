"""The report's scenario for gradebook: Ben's grade exports without a crash."""

import unittest

from gradebook.final import letter_report

BEN = {
    "homework": [{"points": 9, "max": 10}, {"points": 10, "max": 10}],
    "exams": [
        {"points": 9, "max": 10},
        {"points": 8, "max": 10},
        {"points": 42, "max": 50},
    ],
}


class ReportedCase(unittest.TestCase):
    def test_bens_grade_exports(self):
        letter_report({"ben": BEN})


if __name__ == "__main__":
    unittest.main()
