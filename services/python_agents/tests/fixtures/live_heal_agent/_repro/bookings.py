"""The report's scenario for bookings: back-to-back stays in room 12."""

import unittest
from datetime import date

from bookings.booking import book
from bookings.rooms import Room


class ReportedCase(unittest.TestCase):
    def test_back_to_back(self):
        room = Room(12, nightly_cents=8000)
        book(room, date(2026, 5, 1), date(2026, 5, 3))
        book(room, date(2026, 5, 3), date(2026, 5, 5))


if __name__ == "__main__":
    unittest.main()
