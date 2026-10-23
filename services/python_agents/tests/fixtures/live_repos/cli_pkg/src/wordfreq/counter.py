"""The hot path: counting words with a list of pairs."""


def count_words(words: list[str]) -> list[tuple[str, int]]:
    """Return ``(word, count)`` pairs in first-occurrence order."""
    pairs: list[tuple[str, int]] = []
    for word in words:
        for index, (seen, total) in enumerate(pairs):
            if seen == word:
                pairs[index] = (seen, total + 1)
                break
        else:
            pairs.append((word, 1))
    return pairs


def top(pairs: list[tuple[str, int]], limit: int) -> list[tuple[str, int]]:
    """Return the ``limit`` most frequent pairs, ties in first-occurrence order."""
    ranked = list(pairs)
    for i in range(len(ranked)):
        for j in range(len(ranked) - 1 - i):
            if ranked[j][1] < ranked[j + 1][1]:
                ranked[j], ranked[j + 1] = ranked[j + 1], ranked[j]
    return ranked[:limit]
