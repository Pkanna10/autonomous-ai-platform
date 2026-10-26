"""Tests for ``tripsheet`` (stdlib ``unittest``)."""

import unittest

from tripsheet.data import line, records
from tripsheet.report import summarise

LINES = [
    line("T1", "north", 1200, 250, 1, "bus", 8),
    line("T2", "south", 800, 180, 4, "tram", 23),
    line("T3", "north", 4100, 620, 2, "bus", 1),
    line("T4", "east", 300, 90, 5, "bus", 13),
]


class SummaryTests(unittest.TestCase):
    def test_summary(self) -> None:
        self.assertEqual(
            summarise(LINES),
            {
                "distance km": "6.400",
                "fare north": "8.70",
                "fare south": "1.80",
                "fare east": "0.90",
                "busiest mode": "bus",
                "longest trip": "T3",
                "fare per km": "1.7812",
                "crowded share": "0.500",
                "night trips": "2",
                "short-hop fares": "2.70",
            },
        )

    def test_one_record(self) -> None:
        summary = summarise(LINES[:1])
        self.assertEqual(summary["longest trip"], "T1")
        self.assertEqual(summary["night trips"], "0")


class DataTests(unittest.TestCase):
    def test_generation_is_deterministic(self) -> None:
        self.assertEqual(records(25), records(25))
        self.assertEqual(records(25)[3], line("T3", "east", 5057, 812, 2, "metro", 22))


if __name__ == "__main__":
    unittest.main()
