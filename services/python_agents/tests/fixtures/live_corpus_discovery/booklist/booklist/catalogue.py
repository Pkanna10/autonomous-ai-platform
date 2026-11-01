"""The catalogue of titles on sale."""


class Catalogue:
    def __init__(self, titles: list[str]) -> None:
        self._titles = list(titles)

    def add(self, title: str) -> None:
        self._titles.append(title)

    def ordered(self) -> list[str]:
        """Every title, in alphabetical order."""
        return sorted(self._titles)

    def __len__(self) -> int:
        return len(self._titles)
