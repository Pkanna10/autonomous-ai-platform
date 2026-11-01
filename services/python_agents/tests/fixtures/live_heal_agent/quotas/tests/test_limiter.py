import unittest

from quotas.config import parse_duration
from quotas.limiter import Limiter, QuotaExceededError


class LimiterTest(unittest.TestCase):
    def test_the_quota_is_enforced(self):
        limiter = Limiter(3, "1m")
        for now in (0, 1, 2):
            limiter.acquire("acme", now)
        with self.assertRaises(QuotaExceededError):
            limiter.acquire("acme", 3)

    def test_clients_have_their_own_quota(self):
        limiter = Limiter(1, "30s")
        limiter.acquire("acme", 0)
        limiter.acquire("globex", 0)

    def test_durations(self):
        self.assertEqual(parse_duration("250ms"), 250)
        self.assertEqual(parse_duration("2s"), 2000)
        with self.assertRaises(ValueError):
            parse_duration("2 days")


if __name__ == "__main__":
    unittest.main()
