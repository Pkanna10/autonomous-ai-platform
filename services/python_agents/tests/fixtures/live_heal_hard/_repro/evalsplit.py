"""The report's scenario for evalsplit, pinned: seed 3 is one that crashed."""

import unittest

from evalsplit.evaluate import evaluate

MAIL = (
    [{"id": i, "label": "spam"} for i in range(8)]
    + [{"id": 10 + i, "label": "ham"} for i in range(8)]
    + [{"id": 20 + i, "label": "phish"} for i in range(3)]
)


class ReportedCase(unittest.TestCase):
    def test_the_nightly_evaluation_runs(self):
        evaluate(MAIL, lambda row: row["label"], seed=3)


if __name__ == "__main__":
    unittest.main()
