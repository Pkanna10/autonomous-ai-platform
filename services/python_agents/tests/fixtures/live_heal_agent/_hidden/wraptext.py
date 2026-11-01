"""Hidden check for wraptext: long words are split, never past the width."""

import unittest

from wraptext.layout import paragraph
from wraptext.wrap import wrap

LINK = "https://example.org/reports/2026/annual-summary"


class HiddenCheck(unittest.TestCase):
    def test_the_report_paragraph(self):
        text = f"Read the report at {LINK} today"
        lines = paragraph(text, 30).split("\n")
        self.assertTrue(all(len(line) <= 30 for line in lines), lines)
        self.assertEqual("".join(lines).replace(" ", ""), text.replace(" ", ""))

    def test_a_long_word_is_split_by_the_width(self):
        self.assertEqual(wrap("abcdefghij", 4), ["abcd", "efgh", "ij"])

    def test_indented_lines_keep_the_width(self):
        lines = paragraph("see " + LINK, 20, "  ").split("\n")
        self.assertTrue(all(len(line) <= 20 for line in lines), lines)


if __name__ == "__main__":
    unittest.main()
