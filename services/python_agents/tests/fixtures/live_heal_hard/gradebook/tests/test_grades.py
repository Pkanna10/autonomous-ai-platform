import unittest

from gradebook.final import final_score, letter_report
from gradebook.letters import letter_for
from gradebook.scores import category_percent

ANA = {
    "homework": [{"points": 8, "max": 10}, {"points": 10, "max": 10}],
    "exams": [{"points": 35, "max": 50}, {"points": 45, "max": 50}],
}


class GradesTest(unittest.TestCase):
    def test_category_percent(self):
        self.assertEqual(category_percent([{"points": 8, "max": 10}] * 2), 80.0)

    def test_final_score(self):
        self.assertEqual(final_score(ANA), 84.0)

    def test_letters(self):
        self.assertEqual(
            [letter_for(s) for s in (95, 84, 70, 12)], ["A", "B", "C", "F"]
        )

    def test_letter_report(self):
        self.assertEqual(letter_report({"ana": ANA}), {"ana": "B"})


if __name__ == "__main__":
    unittest.main()
