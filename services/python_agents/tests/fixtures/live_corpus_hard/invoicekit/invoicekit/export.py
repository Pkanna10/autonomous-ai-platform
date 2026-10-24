"""Exporting invoices as delimited text for the accounting system."""

from invoicekit.models import Invoice

SEPARATOR = ","
QUOTE = '"'


def quote(field: str) -> str:
    """``field`` quoted when it holds the separator, a quote or a line break."""
    if any(ch in field for ch in (SEPARATOR, QUOTE, "\n", "\r")):
        return QUOTE + field.replace(QUOTE, QUOTE * 2) + QUOTE
    return field


def invoice_rows(invoice: Invoice) -> list[str]:
    """One exported row per line of ``invoice``."""
    rows: list[str] = []
    for position, item in enumerate(invoice.lines, start=1):
        fields = [
            str(invoice.number),
            str(position),
            invoice.customer,
            item.line.sku,
            str(item.line.quantity),
            str(item.net_cents),
            str(item.tax_cents),
        ]
        rows.append(SEPARATOR.join(quote(field) for field in fields))
    return rows


def export(found: list[Invoice]) -> list[str]:
    header = "invoice,position,customer,sku,quantity,net_cents,tax_cents"
    rows = [header]
    for invoice in found:
        rows.extend(invoice_rows(invoice))
    return rows


def digest(rows: list[str]) -> str:
    """A short hexadecimal digest of the exported text (FNV-1a, 64 bit)."""
    value = 0xCBF29CE484222325
    for row in rows:
        for byte in (row + "\n").encode("utf-8"):
            value ^= byte
            value = (value * 0x100000001B3) % (1 << 64)
    return f"{value:016x}"
