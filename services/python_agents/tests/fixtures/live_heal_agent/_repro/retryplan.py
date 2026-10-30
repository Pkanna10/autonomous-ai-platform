"""The report's scenario for retryplan: seed 5 fits the deadline."""

import unittest

from retryplan.schedule import plan


class ReportedCase(unittest.TestCase):
    def test_seed_five(self):
        self.assertEqual(len(plan(6, base=4, cap=8, deadline=48, seed=5)), 6)


if __name__ == "__main__":
    unittest.main()
