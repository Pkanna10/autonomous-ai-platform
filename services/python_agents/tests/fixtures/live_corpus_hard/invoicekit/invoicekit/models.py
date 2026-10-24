"""The typed records the toolkit works with."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RawLine:
    """One parsed (not yet priced) invoice line."""

    invoice: int
    customer: str
    region: str
    sku: str
    family: str
    quantity: int
    unit_cents: int
    day: str


@dataclass(frozen=True)
class PricedLine:
    """A line with its amounts, all in cents."""

    line: RawLine
    gross_cents: int
    discount_cents: int
    net_cents: int
    tax_cents: int

    @property
    def total_cents(self) -> int:
        return self.net_cents + self.tax_cents


@dataclass
class Invoice:
    """The lines of one invoice number, for one customer."""

    number: int
    customer: str
    lines: list[PricedLine] = field(default_factory=list)

    def add(self, priced: PricedLine) -> None:
        if priced.line.invoice != self.number:
            raise ValueError("line belongs to another invoice")
        self.lines.append(priced)

    @property
    def net_cents(self) -> int:
        return sum(p.net_cents for p in self.lines)

    @property
    def tax_cents(self) -> int:
        return sum(p.tax_cents for p in self.lines)

    @property
    def total_cents(self) -> int:
        return self.net_cents + self.tax_cents

    @property
    def regions(self) -> list[str]:
        return sorted({p.line.region for p in self.lines})


@dataclass(frozen=True)
class Rejection:
    """A raw line the parser refused, and why."""

    number: int
    reason: str
