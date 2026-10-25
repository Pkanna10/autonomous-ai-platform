"""The report's scenario for pagekit: 30 hits, the last page offered opens."""

import unittest

from pagekit.pager import links, render

HITS = [f"hit {i}" for i in range(30)]


class ReportedCase(unittest.TestCase):
    def test_every_offered_page_opens(self):
        for page in links(len(HITS), 10):
            render(HITS, page, 10)


if __name__ == "__main__":
    unittest.main()
