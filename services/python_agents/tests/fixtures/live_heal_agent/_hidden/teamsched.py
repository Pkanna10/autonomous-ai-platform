"""Hidden check for teamsched: ranges include their last day."""

import unittest

from teamsched.scheduler import NoEligibleWorkerError, assign
from teamsched.shifts import Shift
from teamsched.workers import parse_days, worker


class HiddenCheck(unittest.TestCase):
    def test_the_friday_bar_shift(self):
        team = [worker("ana", "mon-fri", "bar,floor"), worker("ben", "sat,sun", "bar")]
        plan = assign(team, [Shift("fri", "bar"), Shift("sat", "bar")])
        self.assertEqual(plan, {Shift("fri", "bar"): "ana", Shift("sat", "bar"): "ben"})

    def test_ranges_include_both_ends(self):
        self.assertEqual(parse_days("sat-sun"), {"sat", "sun"})
        self.assertEqual(parse_days("mon-wed,fri"), {"mon", "tue", "wed", "fri"})

    def test_no_one_works_a_day_off(self):
        team = [worker("ben", "mon-tue", "bar")]
        with self.assertRaises(NoEligibleWorkerError):
            assign(team, [Shift("wed", "bar")])


if __name__ == "__main__":
    unittest.main()
