"""Row numbers for stock codes."""


class Registry:
    """Stable row numbers for stock codes, in order of first appearance."""

    def __init__(self) -> None:
        self._codes: list[str] = []

    def row(self, code: str) -> int:
        try:
            return self._codes.index(code)
        except ValueError:
            self._codes.append(code)
            return len(self._codes) - 1

    def codes(self) -> list[str]:
        return list(self._codes)
