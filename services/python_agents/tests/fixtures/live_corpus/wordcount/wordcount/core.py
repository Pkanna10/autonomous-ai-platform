"""Word frequencies."""


def frequencies(words: list[str]) -> dict[str, int]:
    """Each distinct word and how often it occurs, words in sorted order."""
    return {word: words.count(word) for word in sorted(set(words))}


def most_common(freq: dict[str, int], limit: int) -> list[tuple[str, int]]:
    """The ``limit`` most frequent words; ties in alphabetical order."""
    return sorted(freq.items(), key=lambda item: (-item[1], item[0]))[:limit]
