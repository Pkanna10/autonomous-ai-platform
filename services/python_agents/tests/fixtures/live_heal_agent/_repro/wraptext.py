"""The report's scenario for wraptext: the paragraph keeps its link."""

import unittest

from wraptext.layout import paragraph

LINK = "https://example.org/reports/2026/annual-summary"


class ReportedCase(unittest.TestCase):
    def test_the_long_link(self):
        text = paragraph(f"Read the report at {LINK} today", 30)
        self.assertIn(LINK, text.replace("\n", ""))


if __name__ == "__main__":
    unittest.main()
