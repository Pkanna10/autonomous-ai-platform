"""Electricity tariffs: what a day's charging costs."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Band:
    name: str
    start_hour: int  # inclusive
    end_hour: int  # exclusive
    cents_per_kwh: int


BANDS = (
    Band("night", 0, 6, 14),
    Band("morning", 6, 10, 31),
    Band("day", 10, 17, 24),
    Band("evening", 17, 21, 36),
    Band("late", 21, 24, 19),
)


def band_at(minute: float, bands: tuple[Band, ...] = BANDS) -> Band:
    """The band in force ``minute`` minutes after midnight (wrapping daily)."""
    hour = int(minute // 60) % 24
    for band in bands:
        if band.start_hour <= hour < band.end_hour:
            return band
    raise ValueError(f"no band covers hour {hour}")


def check_bands(bands: tuple[Band, ...] = BANDS) -> None:
    """The bands must cover the day exactly once, in order."""
    hour = 0
    for band in bands:
        if band.start_hour != hour or band.end_hour <= band.start_hour:
            raise ValueError(f"band {band.name} does not continue at hour {hour}")
        hour = band.end_hour
    if hour != 24:
        raise ValueError("the bands do not reach midnight")


def charge_cost(kwh: float, start_minute: float, minutes: float) -> int:
    """Cents for ``kwh`` delivered evenly over ``minutes`` from ``start_minute``,
    priced band by band (whole minutes)."""
    if minutes <= 0:
        return 0
    whole = max(1, int(minutes))
    per_minute = kwh / whole
    cents = 0.0
    for step in range(whole):
        cents += per_minute * band_at(start_minute + step).cents_per_kwh
    return round(cents)


def cost_by_band(sessions: list[tuple[float, float, float]]) -> dict[str, int]:
    """Cents per band for ``(start minute, minutes, kWh)`` sessions."""
    totals = {band.name: 0 for band in BANDS}
    for start, minutes, kwh in sessions:
        totals[band_at(start).name] += charge_cost(kwh, start, minutes)
    return totals
