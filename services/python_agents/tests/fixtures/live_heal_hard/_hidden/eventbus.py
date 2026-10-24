"""Hidden check for eventbus: handlers are registered under their event."""

import unittest

from eventbus import shop
from eventbus.dispatch import UnknownEventError, publish
from eventbus.registry import handlers_for

ORDER = {"id": 7, "total": 42.5, "lines": [{"qty": 2}, {"qty": 1}]}


class HiddenCheck(unittest.TestCase):
    def test_paying_runs_both_handlers_in_order(self):
        del shop.OUTBOX[:]
        self.assertEqual(
            publish("order.paid", ORDER), ["receipt", "reserved 3 item(s)"]
        )
        self.assertEqual(shop.OUTBOX, ["receipt for order 7: 42.50 EUR"])

    def test_a_refund_releases_the_stock(self):
        self.assertEqual(publish("order.refunded", ORDER), ["released 3 item(s)"])

    def test_handlers_are_listed_under_their_event(self):
        self.assertEqual(
            handlers_for("order.paid"), [shop.send_receipt, shop.reserve_stock]
        )

    def test_a_misspelt_event_is_still_refused(self):
        with self.assertRaises(UnknownEventError):
            publish("order.payed", ORDER)


if __name__ == "__main__":
    unittest.main()
