"""The report's scenario for routeplan: depot to mill is 3 km."""

import unittest

from routeplan.graph import parse
from routeplan.plan import route_length

NETWORK = "depot-farm:1\ndepot-bridge:4\nfarm-bridge:1\nmill-bridge:1\n"


class ReportedCase(unittest.TestCase):
    def test_depot_to_mill(self):
        self.assertEqual(route_length(parse(NETWORK), ["depot", "mill"]), 3.0)


if __name__ == "__main__":
    unittest.main()
