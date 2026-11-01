import unittest

from teamsched.scheduler import NoEligibleWorkerError, assign
from teamsched.shifts import Shift
from teamsched.workers import parse_days, worker


class SchedulerTest(unittest.TestCase):
    def test_days_as_a_list(self):
        self.assertEqual(parse_days("mon, wed"), {"mon", "wed"})

    def test_the_load_is_spread(self):
        team = [worker("ana", "mon,tue", "bar"), worker("ben", "mon,tue", "bar")]
        plan = assign(team, [Shift("mon", "bar"), Shift("tue", "bar")])
        self.assertEqual(sorted(plan.values()), ["ana", "ben"])

    def test_a_skill_no_one_has_is_refused(self):
        with self.assertRaises(NoEligibleWorkerError):
            assign([worker("ana", "mon", "bar")], [Shift("mon", "kitchen")])


if __name__ == "__main__":
    unittest.main()
