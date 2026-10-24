"""The report renderer."""


class Report:
    """A text report built one row at a time."""

    def __init__(self, title: str) -> None:
        self.text = title + "\n" + "=" * len(title) + "\n"

    def add_row(self, cells: list[str]) -> None:
        """Append one row of ``cells`` separated by `` | ``."""
        self.text += " | ".join(cells) + "\n"

    def add_total(self, label: str, cents: int) -> None:
        self.text += f"{label}: {cents // 100}.{cents % 100:02d}\n"


def render(rows: list[tuple[int, str, int]]) -> str:
    """The full report for ``rows``."""
    report = Report("Sales")
    total = 0
    for sale, region, cents in rows:
        report.add_row([f"{sale:07d}", region.ljust(8), f"{cents:>8d}"])
        total += cents
    report.add_total("total", total)
    return report.text
