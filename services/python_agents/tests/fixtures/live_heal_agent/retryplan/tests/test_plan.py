import unittest

from retryplan.backoff import delays
from retryplan.schedule import DeadlineError, plan


class PlanTest(unittest.TestCase):
    def test_delays_double_with_jitter(self):
        waits = delays(4, 1, 100, seed=1)
        for i, wait in enumerate(waits):
            self.assertTrue(0.5 * 2**i <= wait < 1.5 * 2**i, (i, wait))

    def test_the_jitter_is_reproducible(self):
        self.assertEqual(delays(5, 2, 50, seed=3), delays(5, 2, 50, seed=3))

    def test_a_short_plan_fits(self):
        self.assertEqual(len(plan(3, 1, 4, 12, seed=0)), 3)

    def test_a_deadline_too_short_for_the_cap_is_refused(self):
        with self.assertRaises(DeadlineError):
            plan(6, 4, 8, 47)


if __name__ == "__main__":
    unittest.main()
