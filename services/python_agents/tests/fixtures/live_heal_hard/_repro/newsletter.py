"""The report's scenario for newsletter: a plus address subscribes."""

import unittest

from newsletter.subscribers import Subscribers


class ReportedCase(unittest.TestCase):
    def test_a_plus_address_subscribes(self):
        Subscribers().subscribe("ann+news@example.com", "Ann")


if __name__ == "__main__":
    unittest.main()
