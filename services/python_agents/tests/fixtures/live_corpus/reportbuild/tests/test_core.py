"""Tests for ``reportbuild.core`` (stdlib ``unittest``)."""

import unittest

from reportbuild.core import Report, render


class ReportTests(unittest.TestCase):
    def test_rows_and_total(self) -> None:
        text = render([(1, "north", 1250), (2, "south", 5)])
        self.assertEqual(
            text,
            "Sales\n=====\n"
            "0000001 | north    |     1250\n"
            "0000002 | south    |        5\n"
            "total: 12.55\n",
        )

    def test_title_underline(self) -> None:
        self.assertEqual(Report("Ab").text, "Ab\n==\n")


if __name__ == "__main__":
    unittest.main()
