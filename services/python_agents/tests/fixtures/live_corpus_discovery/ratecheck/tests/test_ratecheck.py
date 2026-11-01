"""Tests for ``ratecheck`` (stdlib ``unittest``)."""

import unittest

from ratecheck.data import conversions
from ratecheck.field import MODULUS, fraction, inverse
from ratecheck.ledger import by_pair, day_print, fingerprints


class FieldTests(unittest.TestCase):
    def test_inverse(self) -> None:
        for value in (1, 2, 12345, MODULUS - 1, 10**30 - 7):
            self.assertEqual(value * inverse(value) % MODULUS, 1)
        with self.assertRaises(ZeroDivisionError):
            inverse(MODULUS)

    def test_fraction(self) -> None:
        self.assertEqual(fraction(6, 3), 2)
        self.assertEqual(fraction(1, 2) * 2 % MODULUS, 1)


class LedgerTests(unittest.TestCase):
    def test_fingerprints_and_totals(self) -> None:
        day = [("A", 6, 3), ("B", 1, 2), ("A", 10, 5)]
        prints = fingerprints(day)
        self.assertEqual(prints, [2, (MODULUS + 1) // 2, 2])
        self.assertEqual(by_pair(day, prints), {"A": (2, 4), "B": (1, prints[1])})
        self.assertEqual(day_print([1, 2]), 1_000_005)
        self.assertEqual(fingerprints([]), [])


class DataTests(unittest.TestCase):
    def test_generation_is_deterministic(self) -> None:
        self.assertEqual(conversions(50), conversions(50))
        self.assertTrue(all(0 < d < 10**30 for _, _, d in conversions(50)))


if __name__ == "__main__":
    unittest.main()
