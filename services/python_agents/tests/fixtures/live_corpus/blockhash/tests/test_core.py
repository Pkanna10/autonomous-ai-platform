"""Tests for ``blockhash.core`` (stdlib ``unittest``)."""

import hashlib
import unittest

from blockhash.core import BLOCK, image_digest


class DigestTests(unittest.TestCase):
    def test_block_size(self) -> None:
        self.assertEqual(len(BLOCK), 1 << 20)

    def test_two_blocks(self) -> None:
        expected = hashlib.sha256(
            BLOCK + b"\x00\x00\x00\x00" + BLOCK + b"\x00\x00\x00\x01"
        ).hexdigest()
        self.assertEqual(image_digest(2), expected)


if __name__ == "__main__":
    unittest.main()
