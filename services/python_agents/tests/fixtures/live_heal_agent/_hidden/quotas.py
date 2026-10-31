"""Hidden check for quotas: windows of any unit expire on time."""

import unittest

from quotas.config import parse_duration
from quotas.limiter import Limiter, QuotaExceededError


class HiddenCheck(unittest.TestCase):
    def test_a_one_minute_window_expires(self):
        limiter = Limiter(5, "1m")
        for now in (0, 1, 2, 3, 4):
            limiter.acquire("acme", now)
        limiter.acquire("acme", 130)

    def test_a_thirty_second_window_slides(self):
        limiter = Limiter(2, "30s")
        limiter.acquire("acme", 0)
        limiter.acquire("acme", 10)
        with self.assertRaises(QuotaExceededError):
            limiter.acquire("acme", 20)
        limiter.acquire("acme", 31)
        with self.assertRaises(QuotaExceededError):
            limiter.acquire("acme", 35)

    def test_durations_stay_in_milliseconds(self):
        self.assertEqual(parse_duration("1m"), 60_000)
        self.assertEqual(parse_duration("2h"), 7_200_000)


if __name__ == "__main__":
    unittest.main()
