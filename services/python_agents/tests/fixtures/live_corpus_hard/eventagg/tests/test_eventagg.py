"""Tests for ``eventagg`` (stdlib ``unittest``)."""

import unittest

from eventagg.aggregate import error_share, totals
from eventagg.events import KINDS, generate


class AggregateTests(unittest.TestCase):
    def test_totals_per_key(self) -> None:
        events: list[dict[str, object]] = [
            {"kind": "b", "bytes": 5, "latency_ms": 1.5, "status": 200},
            {"kind": "a", "bytes": 2, "latency_ms": 9.0, "status": 500},
            {"kind": "b", "bytes": 1, "latency_ms": 3.0, "status": 404},
        ]
        self.assertEqual(totals(events, "kind"), {"a": (1, 2, 9.0), "b": (2, 6, 3.0)})
        self.assertAlmostEqual(error_share(events), 2 / 3)
        self.assertEqual(error_share([]), 0.0)

    def test_generated_day(self) -> None:
        day = generate(500)
        self.assertEqual(day, generate(500))
        self.assertEqual(sum(c for c, _, _ in totals(day, "kind").values()), 500)
        self.assertLessEqual(set(totals(day, "kind")), set(KINDS))


if __name__ == "__main__":
    unittest.main()
