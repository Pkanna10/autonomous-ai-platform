"""Hidden check for pagekit: exact multiples and the empty result."""

import unittest

from pagekit.pager import links, render
from pagekit.pages import PageError, get_page, page_count

HITS = [f"hit {i}" for i in range(30)]


class HiddenCheck(unittest.TestCase):
    def test_the_last_page_of_an_exact_multiple(self):
        last = page_count(len(HITS), 10)
        self.assertEqual(get_page(HITS, last, 10), HITS[20:])
        self.assertEqual(last, 3)

    def test_counts_around_the_multiples(self):
        counts = [page_count(n, 10) for n in (1, 9, 10, 11, 20, 21, 30, 31)]
        self.assertEqual(counts, [1, 1, 1, 2, 2, 3, 3, 4])
        self.assertEqual(links(30, 10), [1, 2, 3])

    def test_an_empty_result_has_one_page(self):
        self.assertEqual(page_count(0, 10), 1)
        self.assertEqual(get_page([], 1, 10), [])
        self.assertEqual(render([], 1, 10), "Page 1 of 1")
        self.assertEqual(links(0, 10), [1])

    def test_a_page_past_the_end_is_refused(self):
        with self.assertRaises(PageError):
            get_page(HITS, 4, 10)


if __name__ == "__main__":
    unittest.main()
