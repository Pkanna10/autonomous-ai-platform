"""Near-duplicate documents: word shingles and their Jaccard similarity."""

from textindex.tokens import tokens

SHINGLE = 3


def shingles(text: str, size: int = SHINGLE) -> set[tuple[str, ...]]:
    """Every run of ``size`` consecutive words of ``text``."""
    words = [token.text for token in tokens(text)]
    return {tuple(words[i : i + size]) for i in range(len(words) - size + 1)}


def jaccard(a: set[tuple[str, ...]], b: set[tuple[str, ...]]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def near_duplicates(
    texts: list[tuple[int, str]], threshold: float
) -> list[tuple[int, int, float]]:
    """Pairs ``(first, second, similarity)`` at or above ``threshold``,
    in document order."""
    prepared = [(number, shingles(text)) for number, text in texts]
    pairs: list[tuple[int, int, float]] = []
    for i, (first, a) in enumerate(prepared):
        for second, b in prepared[i + 1 :]:
            value = jaccard(a, b)
            if value >= threshold:
                pairs.append((first, second, round(value, 4)))
    return pairs


def most_similar(texts: list[tuple[int, str]]) -> tuple[int, int, float] | None:
    """The most similar pair; the earliest on a tie."""
    best: tuple[int, int, float] | None = None
    for pair in near_duplicates(texts, 0.0):
        if best is None or pair[2] > best[2]:
            best = pair
    return best
