"""The regional tax schedule.

The schedule is kept as text, the way the finance team publishes it: one row
per region and product family with the rate in basis points and the day it
takes effect. A family missing for a region takes the region's ``*`` row.
"""

from dataclasses import dataclass

SCHEDULE = """\
# region family  basis_points effective
AT * 2000 2026-01-01
AT kitchen 1000 2026-01-01
BE * 2100 2026-01-01
BE paint 600 2026-07-01
BG * 2000 2026-01-01
CY * 1900 2026-01-01
CZ * 2100 2026-01-01
CZ garden 1200 2026-01-01
DE * 1900 2026-01-01
DE kitchen 700 2026-01-01
DK * 2500 2026-01-01
EE * 2200 2026-01-01
EE * 2400 2026-10-15
ES * 2100 2026-01-01
ES lighting 1000 2026-01-01
FI * 2550 2026-01-01
FR * 2000 2026-01-01
FR garden 1000 2026-01-01
FR kitchen 550 2026-01-01
GR * 2400 2026-01-01
HR * 2500 2026-01-01
HU * 2700 2026-01-01
IE * 2300 2026-01-01
IE tools 1350 2026-01-01
IT * 2200 2026-01-01
IT kitchen 1000 2026-01-01
LT * 2100 2026-01-01
LU * 1700 2026-01-01
LV * 2100 2026-01-01
MT * 1800 2026-01-01
NL * 2100 2026-01-01
NL garden 900 2026-01-01
PL * 2300 2026-01-01
PL storage 800 2026-01-01
PT * 2300 2026-01-01
RO * 1900 2026-01-01
RO * 2100 2026-10-10
SE * 2500 2026-01-01
SE kitchen 1200 2026-01-01
SI * 2200 2026-01-01
SK * 2000 2026-01-01
SK * 2300 2026-10-20
"""


@dataclass(frozen=True)
class Rate:
    region: str
    family: str
    basis_points: int
    effective: str


def parse_schedule(text: str) -> list[Rate]:
    """The rows of ``text``; comments and blank lines are skipped."""
    rates: list[Rate] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        row = raw.strip()
        if not row or row.startswith("#"):
            continue
        parts = row.split()
        if len(parts) != 4:
            raise ValueError(f"schedule row {number}: expected 4 fields")
        region, family, points, effective = parts
        if not points.isdigit():
            raise ValueError(f"schedule row {number}: rate is not a number")
        rates.append(Rate(region, family, int(points), effective))
    return rates


def known_regions() -> set[str]:
    """Every region the schedule has a row for."""
    return {rate.region for rate in parse_schedule(SCHEDULE)}


def tax_rate(region: str, family: str, day: str) -> int:
    """The rate in basis points for ``family`` sold in ``region`` on ``day``
    (ISO dates compare as text): the latest row in effect, the family's own
    row before the region's ``*`` row."""
    best: Rate | None = None
    for wanted in (family, "*"):
        for rate in parse_schedule(SCHEDULE):
            if rate.region != region or rate.family != wanted:
                continue
            if rate.effective > day:
                continue
            if best is None or rate.effective >= best.effective:
                best = rate
        if best is not None:
            return best.basis_points
    raise KeyError(f"no tax rate for {region}/{family} on {day}")
