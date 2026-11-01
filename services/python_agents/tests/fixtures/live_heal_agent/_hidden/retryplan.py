"""Hidden check for retryplan: the cap holds after the jitter."""

import unittest

from retryplan.backoff import delays
from retryplan.schedule import DeadlineError, plan


class HiddenCheck(unittest.TestCase):
    def test_every_seed_fits_the_promised_deadline(self):
        for seed in range(200):
            self.assertEqual(len(plan(6, 4, 8, 48, seed=seed)), 6)

    def test_no_wait_is_longer_than_the_cap(self):
        for seed in range(100):
            self.assertLessEqual(max(delays(6, 4, 8, seed=seed)), 8)

    def test_the_jitter_still_spreads_short_waits_both_ways(self):
        waits = [delays(1, 2, 100, seed=seed)[0] for seed in range(50)]
        self.assertTrue(min(waits) < 2 < max(waits))

    def test_a_deadline_too_short_is_still_refused(self):
        with self.assertRaises(DeadlineError):
            plan(6, 4, 8, 40, seed=0)


if __name__ == "__main__":
    unittest.main()
