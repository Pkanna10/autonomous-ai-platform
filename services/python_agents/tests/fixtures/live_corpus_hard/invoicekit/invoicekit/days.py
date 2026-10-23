"""Days of the month: weekdays and ISO-style week numbers, without a
calendar library (the rules are simple for the Gregorian calendar)."""

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def split_day(day: str) -> tuple[int, int, int]:
    """``"2026-10-23"`` as ``(2026, 10, 23)``."""
    year, month, date = day.split("-")
    return int(year), int(month), int(date)


def is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def days_in_month(year: int, month: int) -> int:
    if month == 2:
        return 29 if is_leap(year) else 28
    return 30 if month in (4, 6, 9, 11) else 31


def weekday(day: str) -> int:
    """0 for Monday through 6 for Sunday (Zeller's congruence)."""
    year, month, date = split_day(day)
    if month < 3:
        month += 12
        year -= 1
    century, rest = divmod(year, 100)
    h = (
        date + 13 * (month + 1) // 5 + rest + rest // 4 + century // 4 + 5 * century
    ) % 7
    return (h + 5) % 7


def day_of_year(day: str) -> int:
    year, month, date = split_day(day)
    return sum(days_in_month(year, m) for m in range(1, month)) + date


def week_number(day: str) -> int:
    """The ISO week number of ``day``."""
    ordinal = day_of_year(day)
    week = (ordinal - weekday(day) + 9) // 7
    if week < 1:
        return 52
    return week


def by_weekday(amounts: list[tuple[str, int]]) -> dict[str, int]:
    """Sum the ``(day, cents)`` pairs per weekday name, Monday first."""
    totals = [0] * 7
    for day, cents in amounts:
        totals[weekday(day)] += cents
    return {name: totals[i] for i, name in enumerate(WEEKDAYS)}


def by_week(amounts: list[tuple[str, int]]) -> dict[int, int]:
    """Sum the ``(day, cents)`` pairs per week number, in week order."""
    totals: dict[int, int] = {}
    for day, cents in amounts:
        week = week_number(day)
        totals[week] = totals.get(week, 0) + cents
    return dict(sorted(totals.items()))
