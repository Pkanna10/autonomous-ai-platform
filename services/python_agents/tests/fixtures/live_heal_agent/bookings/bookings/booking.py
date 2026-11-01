"""Booking a stay."""

from bookings.billing import stay_price
from bookings.stay import nights


def book(room, check_in, check_out):
    """Reserve the stay's nights in ``room`` and return its price in cents."""
    dates = nights(check_in, check_out)
    room.reserve(dates)
    return stay_price(room, dates)
