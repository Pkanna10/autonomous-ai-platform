"""Tests for ``logarchive`` (stdlib ``unittest``)."""

import unittest
import zlib

from logarchive.archive import CHECKPOINT_EVERY, PIECE, pack
from logarchive.data import WORDS, day_log


class ArchiveTests(unittest.TestCase):
    def test_the_archive_is_one_deflate_stream(self) -> None:
        log = day_log(5000)
        archive, _ = pack(log)
        self.assertEqual(zlib.decompress(archive), log)
        self.assertEqual(archive, zlib.compress(log, 9))

    def test_checkpoints(self) -> None:
        log = day_log(200000)
        archive, checkpoints = pack(log)
        self.assertEqual(len(checkpoints), len(log) // (PIECE * CHECKPOINT_EVERY))
        self.assertEqual(checkpoints, sorted(checkpoints))
        self.assertLess(checkpoints[-1], len(archive))
        self.assertEqual(pack(b""), (zlib.compress(b"", 9), []))


class DataTests(unittest.TestCase):
    def test_generation_is_deterministic(self) -> None:
        self.assertEqual(day_log(100), day_log(100))
        self.assertEqual(len(set(WORDS)), 256)
        self.assertEqual(len(day_log(100).split(b" ")), 100)


if __name__ == "__main__":
    unittest.main()
