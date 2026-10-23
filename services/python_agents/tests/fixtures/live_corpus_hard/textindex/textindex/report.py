"""Printing query results."""

from textindex.index import Index
from textindex.query import evaluate, parse, positive_terms
from textindex.ranking import rank
from textindex.snippets import snippet


def answer(index: Index, text: str, top: int) -> list[str]:
    query = parse(text)
    matched = evaluate(index, query)
    terms = positive_terms(query)
    lines = [f"query {text!r}: {len(matched)} match(es)"]
    for document, value in rank(index, matched, terms, top):
        lines.append(f"  {document:4d}  {value:7.4f}  {index.titles[document]}")
        lines.append(f"        {snippet(index.texts[document], terms)}")
    return lines


def summary(index: Index) -> list[str]:
    return [
        f"documents {index.documents}",
        f"terms {len(index.postings)}",
        f"mean length {index.mean_length:.2f}",
    ]
