"""Tests for ``fleetsim`` (stdlib ``unittest``)."""

import unittest

from fleetsim.agenda import Agenda
from fleetsim.checks import check_fleet, check_outcomes
from fleetsim.dispatch import choose
from fleetsim.feed import Job, depots, jobs, past_waits, vehicles
from fleetsim.fleet import Vehicle, utilisation
from fleetsim.geometry import Point, blocks, bounding_box, travel_minutes, zone_of
from fleetsim.metrics import histogram, mean, percentile, share_at_most, spread
from fleetsim.service import on_time_by_tier, per_job, worst_standing
from fleetsim.simulation import run_day
from fleetsim.tariffs import band_at, charge_cost, check_bands
from fleetsim.timeline import peak_hour, sparkline


class GeometryTests(unittest.TestCase):
    def test_distances_and_zones(self) -> None:
        self.assertEqual(blocks(Point(1, 2), Point(-2, 6)), 7)
        self.assertEqual(travel_minutes(Point(0, 0), Point(0, 0)), 0.0)
        self.assertEqual(zone_of(Point(1, 1)), "core")
        self.assertEqual(zone_of(Point(30, 0)), "ring")
        self.assertEqual(zone_of(Point(60, 0)), "outer")
        self.assertEqual(
            bounding_box([Point(3, -1), Point(-2, 4)]), (Point(-2, -1), Point(3, 4))
        )
        with self.assertRaises(ValueError):
            bounding_box([])


class MetricsTests(unittest.TestCase):
    def test_percentiles_and_shares(self) -> None:
        samples = [5.0, 1.0, 4.0, 2.0, 3.0]
        self.assertEqual(percentile(samples, 50), 3.0)
        self.assertEqual(percentile(samples, 100), 5.0)
        self.assertEqual(share_at_most(samples, 2.5), 0.4)
        self.assertEqual(mean(samples), 3.0)
        self.assertAlmostEqual(spread(samples), 2**0.5)
        self.assertEqual(histogram(samples, 2.0, 2), [1, 4])
        with self.assertRaises(ValueError):
            percentile(samples, 0)
        with self.assertRaises(ValueError):
            share_at_most([], 1.0)


class AgendaTests(unittest.TestCase):
    def test_time_order_with_stable_ties(self) -> None:
        agenda = Agenda()
        agenda.add(5.0, "b", 1)
        agenda.add(1.0, "a", 2)
        agenda.add(5.0, "c", 3)
        self.assertEqual(agenda.kinds(), {"a": 1, "b": 1, "c": 1})
        self.assertEqual([agenda.next().subject for _ in range(3)], [2, 1, 3])
        self.assertIsNone(agenda.peek_time())
        with self.assertRaises(IndexError):
            agenda.next()


class SimulationTests(unittest.TestCase):
    def test_a_small_day(self) -> None:
        fleet = vehicles(1)
        offered = jobs(40, 600.0)
        day = run_day(fleet, offered, 600.0)
        self.assertEqual(len(day.outcomes), 40)
        self.assertEqual(check_outcomes(day, offered), [])
        self.assertEqual(check_fleet(fleet), [])
        services = per_job(day.outcomes, past_waits(100))
        self.assertTrue(all(0 <= s.standing <= 1 for s in services))
        tiers = on_time_by_tier(day.outcomes)
        self.assertEqual(sum(total for _, total in tiers.values()), 40)
        self.assertLessEqual(len(worst_standing(services, "standard", 3)), 3)
        self.assertTrue(all(0 <= utilisation(v, 600.0) <= 1 for v in fleet))

    def test_no_vehicle_with_room(self) -> None:
        depot = depots()[0]
        small = Vehicle("tiny", depot, capacity=1, battery_kwh=50.0)
        job = Job(0, 0.0, Point(0, 0), Point(1, 1), parcels=5, tier="standard")
        self.assertIsNone(choose([small], job))


class TariffTests(unittest.TestCase):
    def test_bands(self) -> None:
        check_bands()
        self.assertEqual(band_at(7 * 60).name, "morning")
        self.assertEqual(band_at(25 * 60).name, "night")
        self.assertEqual(charge_cost(10.0, 0.0, 60.0), 140)
        self.assertEqual(charge_cost(10.0, 0.0, 0.0), 0)


class TimelineTests(unittest.TestCase):
    def test_peak_and_sparkline(self) -> None:
        self.assertEqual(peak_hour({7: 3, 8: 5, 9: 5}), 8)
        self.assertEqual(sparkline([0.0, 1.0, 2.0], " -#"), " -#")
        self.assertEqual(sparkline([]), "")


if __name__ == "__main__":
    unittest.main()
