"""Rooms and the nights they are booked."""


class OverbookedError(RuntimeError):
    """A night of the stay is already booked."""


class Room:
    def __init__(self, number, nightly_cents):
        self.number = number
        self.nightly_cents = nightly_cents
        self.booked = set()

    def reserve(self, dates):
        """Book every night in ``dates``; a night already booked refuses the
        whole stay."""
        taken = sorted(day for day in dates if day in self.booked)
        if taken:
            raise OverbookedError(
                f"room {self.number} is already booked on {taken[0].isoformat()}"
            )
        self.booked.update(dates)
