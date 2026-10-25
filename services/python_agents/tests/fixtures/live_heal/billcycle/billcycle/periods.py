"""Billing periods are calendar months."""

import datetime as dt


def month_start(day):
    return day.replace(day=1)


def month_end(day):
    """The last day of ``day``'s month."""
    first_of_next = dt.date(day.year, day.month + 1, 1)
    return first_of_next - dt.timedelta(days=1)


def billing_period(day):
    """The first and last day of the period ``day`` falls in."""
    return month_start(day), month_end(day)


def days_billed(day):
    start, end = billing_period(day)
    return (end - start).days + 1
