"""The nights of a stay."""

import datetime


def nights(check_in, check_out):
    """The nights of a stay: every date from ``check_in`` up to, but not
    including, ``check_out`` (the guest leaves that morning)."""
    days = (check_out - check_in).days
    return [check_in + datetime.timedelta(days=i) for i in range(days)]
