"""Tests for ``meterlog`` (stdlib ``unittest``)."""

import json
import unittest

from meterlog.readings import month
from meterlog.summary import by_band, out_of_limits, parse, top_meters, under_review


def _line(meter: str, hour: int, kwh: int, volts: int) -> str:
    reading = {"meter": meter, "hour": hour, "kwh": kwh, "volts": volts}
    return json.dumps({**reading, "status": "ok"})


LINES = [
    _line("A", 3, 10, 2300),
    _line("B", 8, 5, 2100),
    _line("A", 18, 7, 2300),
    _line("C", 46, 1, 2600),
]


class SummaryTests(unittest.TestCase):
    def test_figures(self) -> None:
        readings = parse(LINES)
        self.assertEqual(
            by_band(readings), {"night": 10, "day": 5, "peak": 7, "evening": 1}
        )
        self.assertEqual(top_meters(readings, 2), [("A", 17), ("B", 5)])
        self.assertEqual(out_of_limits(readings), 2)

    def test_review_sample(self) -> None:
        self.assertEqual(under_review(LINES, 2), [parse(LINES)[0], parse(LINES)[2]])
        self.assertEqual(under_review(LINES, 9), parse(LINES)[:1])


class ReadingTests(unittest.TestCase):
    def test_generation_is_deterministic(self) -> None:
        self.assertEqual(month(40, 7), month(40, 7))
        hours = [json.loads(line)["hour"] for line in month(40, 7)]
        self.assertEqual(hours, sorted(hours))
        self.assertTrue(all(0 <= hour < 720 for hour in hours))


if __name__ == "__main__":
    unittest.main()
