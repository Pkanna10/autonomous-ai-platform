"""The report's scenario for quotas: the sixth request after two minutes."""

import unittest

from quotas.limiter import Limiter


class ReportedCase(unittest.TestCase):
    def test_the_window_expires(self):
        limiter = Limiter(5, "1m")
        for now in (0, 1, 2, 3, 4):
            limiter.acquire("acme", now)
        limiter.acquire("acme", 130)


if __name__ == "__main__":
    unittest.main()
