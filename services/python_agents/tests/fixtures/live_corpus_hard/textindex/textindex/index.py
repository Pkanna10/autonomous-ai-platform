"""The inverted index: term -> document -> positions."""

from dataclasses import dataclass, field

from textindex.library import Document
from textindex.stemmer import stem
from textindex.stopwords import is_stopword
from textindex.tokens import tokens


@dataclass
class Index:
    postings: dict[str, dict[int, list[int]]] = field(default_factory=dict)
    lengths: dict[int, int] = field(default_factory=dict)
    titles: dict[int, str] = field(default_factory=dict)
    texts: dict[int, str] = field(default_factory=dict)

    @property
    def documents(self) -> int:
        return len(self.lengths)

    @property
    def mean_length(self) -> float:
        if not self.lengths:
            return 0.0
        return sum(self.lengths.values()) / len(self.lengths)

    def frequency(self, term: str) -> int:
        """How many documents hold ``term``."""
        return len(self.postings.get(term, {}))

    def positions(self, term: str, document: int) -> list[int]:
        return self.postings.get(term, {}).get(document, [])


def index_terms(text: str) -> list[tuple[str, int]]:
    """The ``(term, position)`` pairs of ``text`` that are indexed."""
    pairs: list[tuple[str, int]] = []
    for token in tokens(text):
        if is_stopword(token.text):
            continue
        pairs.append((stem(token.text), token.position))
    return pairs


def build(documents: list[Document]) -> Index:
    index = Index()
    for document in documents:
        pairs = index_terms(document.text)
        index.lengths[document.number] = len(pairs)
        index.titles[document.number] = document.title
        index.texts[document.number] = document.text
        for term, position in pairs:
            index.postings.setdefault(term, {}).setdefault(document.number, []).append(
                position
            )
    return index


def vocabulary(index: Index, top: int) -> list[tuple[str, int]]:
    """The ``top`` terms held by the most documents; ties alphabetical."""
    ranked = sorted(index.postings, key=lambda t: (-index.frequency(t), t))
    return [(term, index.frequency(term)) for term in ranked[:top]]
