import unittest

from newsletter.subscribers import (
    AlreadySubscribedError,
    InvalidEmailError,
    Subscribers,
)
from newsletter.validate import is_email


class SubscribersTest(unittest.TestCase):
    def test_subscribe(self):
        subs = Subscribers()
        subs.subscribe(" Ann@Example.com", "Ann")
        self.assertTrue(subs.is_subscribed("ann@example.com"))
        self.assertEqual(len(subs), 1)

    def test_a_second_subscription_is_refused(self):
        subs = Subscribers()
        subs.subscribe("bo@example.org", "Bo")
        with self.assertRaises(AlreadySubscribedError):
            subs.subscribe("BO@example.org", "Bo")

    def test_an_invalid_address_is_refused(self):
        with self.assertRaises(InvalidEmailError):
            Subscribers().subscribe("not-an-address", "X")

    def test_plus_is_valid_syntax(self):
        self.assertTrue(is_email("ann+news@example.com"))


if __name__ == "__main__":
    unittest.main()
