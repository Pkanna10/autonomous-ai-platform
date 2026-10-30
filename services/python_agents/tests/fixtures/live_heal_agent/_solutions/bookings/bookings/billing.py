"""Prices of stays."""


def stay_price(room, dates):
    """What a stay costs: the room's nightly rate for each night."""
    return room.nightly_cents * len(dates)
