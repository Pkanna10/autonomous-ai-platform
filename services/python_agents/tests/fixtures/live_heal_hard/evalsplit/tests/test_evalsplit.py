import unittest

from evalsplit.metrics import recall
from evalsplit.split import train_test_split

ROWS = [{"id": i, "label": "a" if i % 2 else "b"} for i in range(12)]


class SplitTest(unittest.TestCase):
    def test_the_parts_cover_every_row_once(self):
        train, test = train_test_split(ROWS, 0.25, seed=3)
        self.assertEqual(sorted(r["id"] for r in train + test), list(range(12)))

    def test_a_seed_makes_the_split_reproducible(self):
        self.assertEqual(
            train_test_split(ROWS, 0.25, seed=5), train_test_split(ROWS, 0.25, seed=5)
        )

    def test_a_label_with_one_row_is_refused(self):
        with self.assertRaises(ValueError):
            train_test_split(ROWS + [{"id": 99, "label": "c"}], 0.25, seed=1)


class RecallTest(unittest.TestCase):
    def test_recall(self):
        rows = [{"label": "a"}, {"label": "a"}, {"label": "b"}]
        self.assertEqual(recall(rows, ["a", "b", "b"], "a"), 0.5)


if __name__ == "__main__":
    unittest.main()
