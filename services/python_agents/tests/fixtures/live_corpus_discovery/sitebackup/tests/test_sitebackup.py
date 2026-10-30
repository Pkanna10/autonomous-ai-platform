"""Tests for ``sitebackup`` (stdlib ``unittest``)."""

import lzma
import random
import unittest

from sitebackup.backup import archive, bundle, fingerprint
from sitebackup.site import SECTIONS, page, render


class BackupTests(unittest.TestCase):
    def test_the_archive_restores_the_bundle(self) -> None:
        site = {"a": ["<p>x</p>\n", "<p>y</p>\n"], "b": []}
        self.assertEqual(bundle(site), b"== a\n<p>x</p>\n<p>y</p>\n== b\n")
        data = archive(site)
        self.assertEqual(lzma.decompress(data), bundle(site))
        self.assertEqual(data, lzma.compress(bundle(site), preset=6))
        self.assertEqual(len(fingerprint(data)), 64)


class SiteTests(unittest.TestCase):
    def test_pages(self) -> None:
        text = page("news", 3, random.Random(1))
        self.assertTrue(text.startswith("<h1>news 3</h1>\n"))
        self.assertEqual(text.count("<p>"), 10)
        self.assertEqual(render(2), render(2))
        self.assertEqual(list(render(1)), list(SECTIONS))


if __name__ == "__main__":
    unittest.main()
