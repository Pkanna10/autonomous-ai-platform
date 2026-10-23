"""Tests for ``invoicekit`` (stdlib ``unittest``)."""

import unittest
from fractions import Fraction

from invoicekit.audit import audit
from invoicekit.customers import per_customer, segment, segments
from invoicekit.days import by_weekday, week_number, weekday
from invoicekit.discounts import describe, tier_for
from invoicekit.export import digest, export, quote
from invoicekit.feed import raw_lines
from invoicekit.ledger import checksum, invoices, largest, totals_by
from invoicekit.models import RawLine
from invoicekit.money import (
    format_cents,
    parse_cents,
    percent_of,
    round_half_even,
    split_evenly,
)
from invoicekit.parsing import parse_all, parse_line
from invoicekit.pricing import price, price_all
from invoicekit.rules import SCHEDULE, known_regions, parse_schedule, tax_rate


def _line(**changes: object) -> RawLine:
    fields: dict[str, object] = {
        "invoice": 1,
        "customer": "Ada",
        "region": "DE",
        "sku": "TOO-100",
        "family": "tools",
        "quantity": 2,
        "unit_cents": 1000,
        "day": "2026-10-05",
    }
    fields.update(changes)
    return RawLine(**fields)


class MoneyTests(unittest.TestCase):
    def test_rounding_ties_to_even(self) -> None:
        self.assertEqual(round_half_even(Fraction(5, 2)), 2)
        self.assertEqual(round_half_even(Fraction(7, 2)), 4)
        self.assertEqual(round_half_even(Fraction(11, 4)), 3)
        self.assertEqual(percent_of(1001, 5000), 500)

    def test_split_and_format(self) -> None:
        self.assertEqual(split_evenly(10, 3), [4, 3, 3])
        self.assertEqual(format_cents(-123456789), "-1,234,567.89 EUR")
        self.assertEqual(parse_cents("12.3"), 1230)
        with self.assertRaises(ValueError):
            parse_cents("1.234")


class RulesTests(unittest.TestCase):
    def test_family_row_wins_over_the_region_default(self) -> None:
        self.assertEqual(tax_rate("DE", "kitchen", "2026-10-01"), 700)
        self.assertEqual(tax_rate("DE", "tools", "2026-10-01"), 1900)

    def test_the_latest_row_in_effect_applies(self) -> None:
        self.assertEqual(tax_rate("EE", "tools", "2026-10-14"), 2200)
        self.assertEqual(tax_rate("EE", "tools", "2026-10-15"), 2400)
        self.assertEqual(tax_rate("BE", "paint", "2026-06-30"), 2100)
        with self.assertRaises(KeyError):
            tax_rate("XX", "tools", "2026-10-01")

    def test_schedule(self) -> None:
        self.assertIn("SK", known_regions())
        self.assertEqual(len(parse_schedule(SCHEDULE)), 42)
        with self.assertRaises(ValueError):
            parse_schedule("DE * x 2026-01-01")


class PricingTests(unittest.TestCase):
    def test_discount_then_tax(self) -> None:
        priced = price(_line(quantity=20, unit_cents=1000))
        self.assertEqual((priced.gross_cents, priced.discount_cents), (20000, 1000))
        self.assertEqual((priced.net_cents, priced.tax_cents), (19000, 3610))
        self.assertEqual(tier_for(9).basis_points, 0)
        self.assertEqual(describe()[1], "from 10 units: 2.50 %")


class ParsingTests(unittest.TestCase):
    def test_rejections_name_the_problem(self) -> None:
        good = "7;Ada;DE;TOO-1;tools;3;250;2026-10-02"
        self.assertEqual(parse_line(good, {"DE"}).quantity, 3)
        parsed, rejected = parse_all([good, "7;Ada", good.replace("DE", "XX")], {"DE"})
        self.assertEqual(len(parsed), 1)
        self.assertEqual([r.number for r in rejected], [2, 3])


class LedgerTests(unittest.TestCase):
    def test_invoices_totals_and_audit(self) -> None:
        lines = [_line(), _line(invoice=2, customer="Ben"), _line(quantity=12)]
        priced = price_all(lines)
        found = invoices(priced)
        self.assertEqual([len(inv.lines) for inv in found], [2, 1])
        self.assertEqual(largest(found, 1)[0].number, 1)
        self.assertEqual(set(totals_by(priced, "region")), {"DE"})
        self.assertEqual(audit(found), [])
        self.assertIsInstance(checksum(found), int)
        stats = per_customer(found)
        self.assertEqual([s.customer for s in stats], ["Ada", "Ben"])
        self.assertEqual(segments(stats)["bronze"], 2)
        self.assertEqual(segment(15_000_000), "gold")
        rows = export(found)
        self.assertEqual(len(rows), 4)
        self.assertEqual(len(digest(rows)), 16)


class DaysTests(unittest.TestCase):
    def test_weekdays_and_weeks(self) -> None:
        self.assertEqual(weekday("2026-10-23"), 4)  # a Friday
        self.assertEqual(weekday("2024-02-29"), 3)
        self.assertEqual(week_number("2026-10-23"), 43)
        self.assertEqual(by_weekday([("2026-10-19", 5)])["Mon"], 5)


class ExportTests(unittest.TestCase):
    def test_quoting(self) -> None:
        self.assertEqual(quote("plain"), "plain")
        self.assertEqual(quote('a,"b"'), '"a,""b"""')


class FeedTests(unittest.TestCase):
    def test_feed_is_deterministic(self) -> None:
        self.assertEqual(raw_lines(300, 20), raw_lines(300, 20))
        _, rejected = parse_all(raw_lines(300, 20), known_regions())
        self.assertTrue(rejected)


if __name__ == "__main__":
    unittest.main()
