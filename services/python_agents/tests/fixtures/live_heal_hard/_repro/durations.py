"""The report's scenario for durations: what the user expects (wrongly)."""

import unittest

from durations.config import load_settings


class ReportedCase(unittest.TestCase):
    def test_a_plain_timeout_loads(self):
        self.assertEqual(load_settings({"timeout": "90"}), {"timeout": 90})


if __name__ == "__main__":
    unittest.main()
