"""Tests for ``auditchain`` (stdlib ``unittest``)."""

import hashlib
import unittest

from auditchain.chain import GENESIS, seal, seal_after, seals
from auditchain.entries import ENTRY_BYTES, week


class ChainTests(unittest.TestCase):
    def test_seal(self) -> None:
        expected = hashlib.blake2b(GENESIS + b"a", digest_size=32).digest()
        self.assertEqual(seal(GENESIS, b"a"), expected)

    def test_seals_chain_every_entry(self) -> None:
        entries = [b"a", b"b", b"c"]
        chained = seals(entries)
        self.assertEqual(chained[0], seal(GENESIS, b"a"))
        self.assertEqual(chained[2], seal(chained[1], b"c"))
        self.assertEqual([seal_after(entries, n) for n in (1, 2, 3)], chained)
        self.assertEqual(seal_after(entries, 0), GENESIS)
        self.assertNotEqual(seals([b"a", b"c", b"b"])[2], chained[2])


class EntryTests(unittest.TestCase):
    def test_generation_is_deterministic(self) -> None:
        self.assertEqual(list(week(3)), list(week(3)))
        self.assertEqual([len(e) for e in week(3)], [ENTRY_BYTES] * 3)
        self.assertEqual(len(set(week(50))), 50)
        self.assertEqual(seal_after(week(5), 2), seals(week(2))[-1])


if __name__ == "__main__":
    unittest.main()
