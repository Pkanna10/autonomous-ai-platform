"""BM25 ranking."""

import math

from textindex.index import Index

K1 = 1.2
B = 0.75


def idf(index: Index, term: str) -> float:
    n = index.frequency(term)
    return math.log(1 + (index.documents - n + 0.5) / (n + 0.5))


def score(index: Index, document: int, terms: list[str]) -> float:
    total = 0.0
    length = index.lengths[document]
    norm = K1 * (1 - B + B * length / index.mean_length)
    for term in terms:
        tf = len(index.positions(term, document))
        if tf:
            total += idf(index, term) * tf * (K1 + 1) / (tf + norm)
    return total


def rank(
    index: Index, documents: set[int], terms: list[str], top: int
) -> list[tuple[int, float]]:
    """The ``top`` documents by score, ties by document number."""
    scored = [(doc, score(index, doc, terms)) for doc in documents]
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    return scored[:top]
