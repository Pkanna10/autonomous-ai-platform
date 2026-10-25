import os
import tempfile
import unittest

from rosterload.parse import load_roster, read_names
from rosterload.teams import split_teams


class ParseTest(unittest.TestCase):
    def test_read_names_skips_blank_lines(self):
        self.assertEqual(read_names(b"Ann\n\n  Bo  \nCy\n"), ["Ann", "Bo", "Cy"])

    def test_load_roster(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "roster.txt")
            with open(path, "wb") as handle:
                handle.write(b"Dee\nEd\n")
            self.assertEqual(load_roster(path), ["Dee", "Ed"])


class TeamsTest(unittest.TestCase):
    def test_split_teams(self):
        self.assertEqual(split_teams(["cy", "Ann", "Bo"], 2), [["Ann", "Bo"], ["cy"]])


if __name__ == "__main__":
    unittest.main()
