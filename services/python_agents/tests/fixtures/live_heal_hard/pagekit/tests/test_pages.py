import unittest

from pagekit.pager import links, render
from pagekit.pages import PageError, get_page, page_count

ITEMS = [f"hit {i}" for i in range(25)]


class PagesTest(unittest.TestCase):
    def test_page_count(self):
        self.assertEqual(page_count(25, 10), 3)
        self.assertEqual(page_count(7, 10), 1)

    def test_get_page(self):
        self.assertEqual(get_page(ITEMS, 3, 10), ITEMS[20:])

    def test_a_page_past_the_end(self):
        with self.assertRaises(PageError):
            get_page(ITEMS, 4, 10)

    def test_links_and_render(self):
        self.assertEqual(links(25, 10), [1, 2, 3])
        self.assertEqual(render(ITEMS[:3], 1, 10).splitlines()[0], "Page 1 of 1")


if __name__ == "__main__":
    unittest.main()
