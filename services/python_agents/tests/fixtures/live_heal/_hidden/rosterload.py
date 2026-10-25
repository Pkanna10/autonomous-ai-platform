"""Hidden check for rosterload: UTF-8 exports load with their accents intact."""

import os
import tempfile
import unittest

from rosterload.parse import load_roster, read_names


class HiddenCheck(unittest.TestCase):
    def test_names_with_accents(self):
        raw = "José\n\nZoë\nÅsa\n".encode()
        self.assertEqual(read_names(raw), ["José", "Zoë", "Åsa"])

    def test_plain_ascii_still_loads(self):
        self.assertEqual(read_names(b"Ann\nBo\n"), ["Ann", "Bo"])

    def test_load_a_utf8_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "roster.txt")
            with open(path, "wb") as handle:
                handle.write("Ana María\nŁukasz\n".encode())
            self.assertEqual(load_roster(path), ["Ana María", "Łukasz"])


if __name__ == "__main__":
    unittest.main()
