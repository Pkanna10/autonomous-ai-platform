"""Hidden check for evalsplit: the split is stratified for every seed."""

import unittest

from evalsplit.evaluate import evaluate
from evalsplit.split import train_test_split

MAIL = (
    [{"id": i, "label": "spam"} for i in range(8)]
    + [{"id": 10 + i, "label": "ham"} for i in range(8)]
    + [{"id": 20 + i, "label": "phish"} for i in range(3)]
)


def perfect(row):
    return row["label"]


class HiddenCheck(unittest.TestCase):
    def test_evaluate_never_crashes(self):
        for seed in range(100):
            scores = evaluate(MAIL, perfect, seed=seed)
            self.assertEqual(scores, {"ham": 1.0, "phish": 1.0, "spam": 1.0})

    def test_every_label_is_in_both_parts(self):
        for seed in range(100):
            train, test = train_test_split(MAIL, 0.25, seed=seed)
            for part in (train, test):
                self.assertEqual({r["label"] for r in part}, {"spam", "ham", "phish"})
            self.assertEqual(
                sorted(r["id"] for r in train + test), sorted(r["id"] for r in MAIL)
            )

    def test_the_test_part_stays_near_the_fraction(self):
        _, test = train_test_split(MAIL, 0.25, seed=0)
        self.assertTrue(3 <= len(test) <= 6, len(test))


if __name__ == "__main__":
    unittest.main()
