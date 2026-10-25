"""The report's scenario for eventbus: publishing order.paid does not crash."""

import unittest

import eventbus.shop  # noqa: F401  (registers the shop's handlers)
from eventbus.dispatch import publish


class ReportedCase(unittest.TestCase):
    def test_paying_an_order_publishes(self):
        publish("order.paid", {"id": 1, "total": 9.0, "lines": [{"qty": 1}]})


if __name__ == "__main__":
    unittest.main()
