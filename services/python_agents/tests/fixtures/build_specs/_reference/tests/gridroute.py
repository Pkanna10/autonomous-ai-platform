import unittest

from gridroute import parse_grid, render, shortest_costs


class GridRouteTest(unittest.TestCase):
    def test_the_worked_example(self):
        text = "3 2\n131\n112\n"
        self.assertEqual(shortest_costs(parse_grid(text)), [[0, 3, 4], [1, 2, 4]])
        self.assertEqual(
            render(text),
            "size=3x2\ncorner 0,0 = 0\ncorner 2,0 = 4\ncorner 0,1 = 1\n"
            "corner 2,1 = 4\ncentre 1,1 = 2\ntotal=14\nmax=4\n",
        )

    def test_a_single_cell(self):
        self.assertEqual(shortest_costs([[7]]), [[0]])

    def test_a_wrong_row_count_raises(self):
        with self.assertRaises(ValueError):
            parse_grid("2 2\n11\n")

    def test_a_zero_digit_raises(self):
        with self.assertRaises(ValueError):
            parse_grid("2 1\n10\n")

    def test_the_final_newline_is_optional(self):
        self.assertEqual(parse_grid("2 1\n12"), [[1, 2]])
