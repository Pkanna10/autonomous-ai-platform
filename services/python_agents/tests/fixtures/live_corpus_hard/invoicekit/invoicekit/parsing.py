"""Raw lines to typed records."""

from invoicekit.models import RawLine, Rejection
from invoicekit.rules import known_regions

FIELDS = 8


def _number(text: str, what: str) -> int:
    if not text.isdigit():
        raise ValueError(f"{what} is not a whole number: {text!r}")
    return int(text)


def _day(text: str) -> str:
    year, month, day = text.split("-")
    if len(year) != 4 or not (1 <= int(month) <= 12) or not (1 <= int(day) <= 31):
        raise ValueError(f"not a day: {text!r}")
    return text


def parse_line(text: str, regions: set[str]) -> RawLine:
    """One raw line; ``ValueError`` names what is wrong with it."""
    fields = text.split(";")
    if len(fields) != FIELDS:
        raise ValueError(f"expected {FIELDS} fields, got {len(fields)}")
    invoice, customer, region, sku, family, quantity, unit, day = fields
    if region not in regions:
        raise ValueError(f"unknown region {region!r}")
    if not customer.strip():
        raise ValueError("no customer")
    parsed = RawLine(
        invoice=_number(invoice, "invoice"),
        customer=customer.strip(),
        region=region,
        sku=sku,
        family=family,
        quantity=_number(quantity, "quantity"),
        unit_cents=_number(unit, "unit price"),
        day=_day(day),
    )
    if parsed.quantity < 1:
        raise ValueError("quantity must be at least 1")
    return parsed


def parse_all(
    lines: list[str], regions: set[str] | None = None
) -> tuple[list[RawLine], list[Rejection]]:
    """Every line parsed, or rejected with its 1-based number and reason;
    ``regions`` defaults to every region of the tax schedule."""
    if regions is None:
        regions = known_regions()
    parsed: list[RawLine] = []
    rejected: list[Rejection] = []
    for number, text in enumerate(lines, start=1):
        try:
            parsed.append(parse_line(text, regions))
        except ValueError as error:
            rejected.append(Rejection(number, str(error)))
    return parsed, rejected
