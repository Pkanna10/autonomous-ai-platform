"""Hidden check for newsletter: a +tag is dropped from the local part only."""

import unittest

from newsletter.normalise import canonical_email
from newsletter.subscribers import AlreadySubscribedError, Subscribers


class HiddenCheck(unittest.TestCase):
    def test_a_plus_address_subscribes(self):
        subs = Subscribers()
        subs.subscribe("ann+news@example.com", "Ann")
        self.assertTrue(subs.is_subscribed("ann@example.com"))
        self.assertTrue(subs.is_subscribed("ANN+other@example.com"))

    def test_the_key_keeps_the_domain(self):
        self.assertEqual(canonical_email(" Ann+News@Example.com "), "ann@example.com")
        self.assertEqual(canonical_email("bo@example.org"), "bo@example.org")

    def test_the_same_inbox_subscribes_once(self):
        subs = Subscribers()
        subs.subscribe("ann@example.com", "Ann")
        with self.assertRaises(AlreadySubscribedError):
            subs.subscribe("ann+news@example.com", "Ann")

    def test_two_people_with_tags_on_different_domains(self):
        subs = Subscribers()
        subs.subscribe("bo+a@example.com", "Bo")
        subs.subscribe("bo+b@another.org", "Bo")
        self.assertEqual(len(subs), 2)
        self.assertFalse(subs.is_subscribed("bo@third.net"))


if __name__ == "__main__":
    unittest.main()
