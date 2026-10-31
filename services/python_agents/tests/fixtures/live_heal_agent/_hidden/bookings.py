"""Hidden check for bookings: the departure day is free, prices per night."""

import unittest
from datetime import date

from bookings.billing import stay_price
from bookings.booking import book
from bookings.rooms import OverbookedError, Room
from bookings.stay import nights


class HiddenCheck(unittest.TestCase):
    def test_back_to_back_stays(self):
        room = Room(12, 8000)
        book(room, date(2026, 5, 1), date(2026, 5, 3))
        self.assertEqual(book(room, date(2026, 5, 3), date(2026, 5, 5)), 16000)

    def test_the_nights_exclude_the_departure_day(self):
        self.assertEqual(
            nights(date(2026, 5, 1), date(2026, 5, 3)),
            [date(2026, 5, 1), date(2026, 5, 2)],
        )

    def test_a_one_night_stay_costs_one_night(self):
        room = Room(4, 9000)
        self.assertEqual(book(room, date(2026, 6, 1), date(2026, 6, 2)), 9000)
        self.assertEqual(room.booked, {date(2026, 6, 1)})
        self.assertEqual(stay_price(room, [date(2026, 6, 9)]), 9000)

    def test_an_overlap_on_the_first_night_is_still_refused(self):
        room = Room(5, 8000)
        book(room, date(2026, 5, 1), date(2026, 5, 4))
        with self.assertRaises(OverbookedError):
            book(room, date(2026, 5, 3), date(2026, 5, 6))


if __name__ == "__main__":
    unittest.main()
