"""Hidden check for routeplan: two-way roads, truly shortest routes."""

import unittest

from routeplan.graph import RouteError, parse
from routeplan.paths import shortest
from routeplan.plan import route_length

NETWORK = "depot-farm:1\ndepot-bridge:4\nfarm-bridge:1\nmill-bridge:1\n"


class HiddenCheck(unittest.TestCase):
    def test_roads_are_two_way(self):
        self.assertEqual(shortest(parse("a-b:2\n"), "b", "a"), 2.0)

    def test_the_shortest_route_is_found(self):
        self.assertEqual(shortest(parse(NETWORK), "depot", "mill"), 3.0)

    def test_a_detour_beats_a_long_direct_road(self):
        network = parse("s-t:10\ns-u:2\nu-v:2\nv-t:2\n")
        self.assertEqual(route_length(network, ["t", "s", "t"]), 12.0)

    def test_unconnected_towns_are_still_refused(self):
        with self.assertRaises(RouteError):
            shortest(parse("a-b:1\nc-d:1\n"), "d", "a")


if __name__ == "__main__":
    unittest.main()
