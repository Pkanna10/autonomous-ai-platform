import unittest

from routeplan.graph import RouteError, parse
from routeplan.paths import shortest
from routeplan.plan import route_length


class RoutesTest(unittest.TestCase):
    def test_a_chain_of_roads(self):
        self.assertEqual(shortest(parse("a-b:2\nb-c:3\n"), "a", "c"), 5.0)

    def test_a_tour(self):
        network = parse("a-b:2\nb-c:3\nc-d:1\n")
        self.assertEqual(route_length(network, ["a", "c", "d"]), 6.0)

    def test_unconnected_towns_are_refused(self):
        with self.assertRaises(RouteError):
            shortest(parse("a-b:1\nc-d:1\n"), "a", "d")


if __name__ == "__main__":
    unittest.main()
