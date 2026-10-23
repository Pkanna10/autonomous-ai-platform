"""Tests for ``deliveryround`` (stdlib ``unittest``)."""

import unittest

from deliveryround.distance import distance_so_far, leg_length
from deliveryround.network import Stop, build_stops, find_stop, legs
from deliveryround.pickups import pending_views


class NetworkTests(unittest.TestCase):
    def test_codes_are_distinct_and_found(self) -> None:
        stops = build_stops(200)
        self.assertEqual(len({s.code for s in stops}), 200)
        self.assertEqual(find_stop(stops, stops[123].code), stops[123])
        with self.assertRaises(KeyError):
            find_stop(stops, "missing")

    def test_legs_use_known_stops(self) -> None:
        stops = build_stops(20)
        codes = {s.code for s in stops}
        for start, end in legs(stops, 50):
            self.assertIn(start, codes)
            self.assertIn(end, codes)


class DistanceTests(unittest.TestCase):
    def test_leg_length(self) -> None:
        self.assertEqual(leg_length(Stop("a", 0, 0, "A"), Stop("b", 3, -4, "B")), 7)

    def test_distance_so_far(self) -> None:
        self.assertEqual(distance_so_far([5, 2, 7]), [0, 5, 7])
        self.assertEqual(distance_so_far([]), [])


class PickupTests(unittest.TestCase):
    def test_views_show_the_lowest_cost_pending(self) -> None:
        offers = [(5, "e"), (3, "c"), (9, "i"), (1, "a"), (3, "b"), (7, "g")]
        self.assertEqual(
            pending_views(offers, 2, 2),
            [[(3, "c"), (5, "e")], [(1, "a"), (3, "c")], [(1, "a"), (3, "b")]],
        )
        self.assertEqual(pending_views([], 2, 2), [])


if __name__ == "__main__":
    unittest.main()
