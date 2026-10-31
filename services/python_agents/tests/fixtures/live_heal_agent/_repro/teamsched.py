"""The report's scenario for teamsched: Ana takes the Friday bar shift."""

import unittest

from teamsched.scheduler import assign
from teamsched.shifts import Shift
from teamsched.workers import worker


class ReportedCase(unittest.TestCase):
    def test_the_week(self):
        team = [worker("ana", "mon-fri", "bar,floor"), worker("ben", "sat,sun", "bar")]
        plan = assign(team, [Shift("fri", "bar"), Shift("sat", "bar")])
        self.assertEqual(plan[Shift("fri", "bar")], "ana")


if __name__ == "__main__":
    unittest.main()
