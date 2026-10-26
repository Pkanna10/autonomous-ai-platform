"""The shop front: catalogue updates and browsing."""

from bisect import bisect_left

from booklist.catalogue import Catalogue
from booklist.links import slug


class Shop:
    def __init__(self, catalogue: Catalogue, size: int) -> None:
        self._catalogue = catalogue
        self._size = size

    def handle(self, command: tuple[str, str]) -> list[str] | None:
        """Add a title (``None``), or list up to ``size`` titles that start
        with a prefix, in alphabetical order, as slugs."""
        action, text = command
        if action == "add":
            self._catalogue.add(text)
            return None
        return self._listing(text)

    def _listing(self, prefix: str) -> list[str]:
        titles = self._catalogue.ordered()
        start = bisect_left(titles, prefix)
        found: list[str] = []
        for title in titles[start : start + self._size]:
            if not title.startswith(prefix):
                break
            found.append(slug(title))
        return found
