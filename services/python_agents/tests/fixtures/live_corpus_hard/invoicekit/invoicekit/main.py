"""Workload: ``python -m invoicekit.main``."""

from invoicekit.audit import audit
from invoicekit.customers import per_customer, repeat_customers, segments, top_customers
from invoicekit.days import by_week, by_weekday
from invoicekit.export import digest, export
from invoicekit.feed import raw_lines
from invoicekit.ledger import checksum, discount_share, invoices, largest, totals_by
from invoicekit.money import format_cents
from invoicekit.parsing import parse_all
from invoicekit.pricing import price_all
from invoicekit.report import largest_section, rejections_section, totals_section


def main() -> None:
    parsed, rejected = parse_all(raw_lines(9000, 700))
    priced = price_all(parsed)
    found = invoices(priced)
    print(f"lines {len(priced)}, invoices {len(found)}")
    for line in totals_section("region", totals_by(priced, "region")):
        print(line)
    for line in totals_section("family", totals_by(priced, "family")):
        print(line)
    for line in largest_section(largest(found, 5)):
        print(line)
    discount, gross = discount_share(priced)
    print(f"discounts {format_cents(discount)} of {format_cents(gross)}")
    amounts = [(item.line.day, item.total_cents) for item in priced]
    for name, cents in by_weekday(amounts).items():
        print(f"{name}  {format_cents(cents)}")
    weeks = by_week(amounts)
    print(
        "weeks " + " ".join(f"{week}:{cents // 100}" for week, cents in weeks.items())
    )
    stats = per_customer(found)
    print(f"customers {len(stats)}, repeat {len(repeat_customers(stats))}")
    print("segments " + " ".join(f"{k}={v}" for k, v in segments(stats).items()))
    for row in top_customers(stats, 3):
        print(f"top {row.customer}  {format_cents(row.total_cents)}")
    print(f"audit findings {len(audit(found))}")
    print(f"export {digest(export(found))}")
    for line in rejections_section(rejected, 4):
        print(line)
    print(f"checksum {checksum(found)}")


if __name__ == "__main__":
    main()
