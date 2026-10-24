"""Hidden check for gradebook: mixed maximums are weighted by their points."""

import unittest

from gradebook.final import final_score, letter_report
from gradebook.letters import letter_for
from gradebook.scores import category_percent

BEN = {
    "homework": [{"points": 9, "max": 10}, {"points": 10, "max": 10}],
    "exams": [
        {"points": 9, "max": 10},
        {"points": 8, "max": 10},
        {"points": 42, "max": 50},
    ],
}


class HiddenCheck(unittest.TestCase):
    def test_the_export_grades_ben(self):
        self.assertEqual(letter_report({"ben": BEN}), {"ben": "B"})

    def test_mixed_maximums(self):
        self.assertAlmostEqual(category_percent(BEN["exams"]), 100 * 59 / 70)
        self.assertAlmostEqual(
            category_percent([{"points": 40, "max": 50}, {"points": 5, "max": 10}]),
            75.0,
        )

    def test_bens_final_score(self):
        self.assertEqual(final_score(BEN), 88.6)

    def test_a_score_over_100_is_still_refused(self):
        with self.assertRaises(ValueError):
            letter_for(100.5)


if __name__ == "__main__":
    unittest.main()
