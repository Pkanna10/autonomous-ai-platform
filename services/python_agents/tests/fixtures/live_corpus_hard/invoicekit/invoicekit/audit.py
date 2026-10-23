"""Consistency checks run before the report is trusted."""

from dataclasses import dataclass

from invoicekit.models import Invoice, PricedLine

MAX_BASIS_POINTS = 3000  # no region in the schedule taxes above 30 %


@dataclass(frozen=True)
class Finding:
    invoice: int
    message: str


def check_line(item: PricedLine) -> list[str]:
    """What is inconsistent about one priced line."""
    problems: list[str] = []
    if item.gross_cents != item.line.quantity * item.line.unit_cents:
        problems.append("gross is not quantity x unit price")
    if item.net_cents != item.gross_cents - item.discount_cents:
        problems.append("net is not gross less discount")
    if item.discount_cents < 0 or item.tax_cents < 0:
        problems.append("negative discount or tax")
    if item.tax_cents * 10000 > item.net_cents * MAX_BASIS_POINTS:
        problems.append("tax above the highest rate")
    return problems


def check_invoice(invoice: Invoice) -> list[str]:
    problems: list[str] = []
    if not invoice.lines:
        problems.append("invoice without lines")
    customers = {item.line.customer for item in invoice.lines}
    if customers != {invoice.customer}:
        problems.append("lines of another customer")
    if invoice.total_cents != sum(item.total_cents for item in invoice.lines):
        problems.append("total is not the sum of its lines")
    return problems


def audit(found: list[Invoice]) -> list[Finding]:
    """Every finding, invoice by invoice, lines first."""
    findings: list[Finding] = []
    for invoice in found:
        for item in invoice.lines:
            for message in check_line(item):
                findings.append(Finding(invoice.number, message))
        for message in check_invoice(invoice):
            findings.append(Finding(invoice.number, message))
    return findings
