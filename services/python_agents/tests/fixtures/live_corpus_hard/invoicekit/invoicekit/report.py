"""The closing report."""

from invoicekit.models import Invoice, Rejection
from invoicekit.money import format_cents


def table(rows: list[list[str]], right: set[int]) -> list[str]:
    """``rows`` as aligned text columns; ``right`` holds the right-aligned
    column numbers. The first row is the header."""
    if not rows:
        return []
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    out: list[str] = []
    for index, row in enumerate(rows):
        cells = [
            cell.rjust(widths[i]) if i in right else cell.ljust(widths[i])
            for i, cell in enumerate(row)
        ]
        out.append("  ".join(cells).rstrip())
        if index == 0:
            out.append("  ".join("-" * w for w in widths))
    return out


def totals_section(title: str, totals: dict[str, tuple[int, int]]) -> list[str]:
    rows = [[title, "net", "tax", "total"]]
    for key, (net, tax) in totals.items():
        rows.append(
            [key, format_cents(net), format_cents(tax), format_cents(net + tax)]
        )
    return table(rows, {1, 2, 3})


def largest_section(found: list[Invoice]) -> list[str]:
    rows = [["invoice", "customer", "lines", "regions", "total"]]
    for invoice in found:
        rows.append(
            [
                str(invoice.number),
                invoice.customer,
                str(len(invoice.lines)),
                ",".join(invoice.regions),
                format_cents(invoice.total_cents),
            ]
        )
    return table(rows, {2, 4})


def rejections_section(rejected: list[Rejection], show: int) -> list[str]:
    lines = [f"rejected lines: {len(rejected)}"]
    for rejection in rejected[:show]:
        lines.append(f"  line {rejection.number}: {rejection.reason}")
    return lines
