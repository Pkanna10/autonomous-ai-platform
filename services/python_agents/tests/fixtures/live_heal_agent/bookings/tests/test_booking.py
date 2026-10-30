import unittest
from datetime import date

from bookings.booking import book
from bookings.rooms import OverbookedError, Room


class BookingTest(unittest.TestCase):
    def test_a_two_night_stay_costs_two_nights(self):
        self.assertEqual(book(Room(1, 8000), date(2026, 5, 1), date(2026, 5, 3)), 16000)

    def test_an_overlapping_stay_is_refused(self):
        room = Room(2, 8000)
        book(room, date(2026, 5, 1), date(2026, 5, 4))
        with self.assertRaises(OverbookedError):
            book(room, date(2026, 5, 2), date(2026, 5, 3))

    def test_separate_stays_in_one_room(self):
        room = Room(3, 5000)
        book(room, date(2026, 5, 1), date(2026, 5, 2))
        self.assertEqual(book(room, date(2026, 5, 10), date(2026, 5, 13)), 15000)


if __name__ == "__main__":
    unittest.main()
