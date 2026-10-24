"""Saving the index as text and reading it back.

One line per posting list: ``term<TAB>doc:pos,pos;doc:pos`` and a header
line with the document lengths. The format is plain text so an index can be
inspected or compared by eye.
"""

from textindex.index import Index

HEADER = "#lengths"


def dump(index: Index) -> list[str]:
    """The index as text lines, terms in alphabetical order."""
    lengths = ",".join(f"{doc}:{n}" for doc, n in sorted(index.lengths.items()))
    lines = [f"{HEADER}\t{lengths}"]
    for term in sorted(index.postings):
        docs = index.postings[term]
        cells = ";".join(
            f"{doc}:{','.join(map(str, positions))}"
            for doc, positions in sorted(docs.items())
        )
        lines.append(f"{term}\t{cells}")
    return lines


def _pairs(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for cell in text.split(";" if ";" in text or ":" in text else ","):
        doc, _, rest = cell.partition(":")
        out.append((int(doc), rest))
    return out


def load(lines: list[str]) -> Index:
    """The index ``dump`` wrote (titles and texts are not stored)."""
    if not lines or not lines[0].startswith(HEADER + "\t"):
        raise ValueError("missing header")
    index = Index()
    lengths = lines[0].split("\t", 1)[1]
    if lengths:
        for cell in lengths.split(","):
            doc, _, count = cell.partition(":")
            index.lengths[int(doc)] = int(count)
    for number, line in enumerate(lines[1:], start=2):
        term, tab, cells = line.partition("\t")
        if not tab or not term:
            raise ValueError(f"line {number}: expected term and postings")
        postings: dict[int, list[int]] = {}
        for doc, positions in _pairs(cells):
            postings[doc] = [int(p) for p in positions.split(",") if p]
        index.postings[term] = postings
    return index


def same_postings(a: Index, b: Index) -> bool:
    """Whether ``a`` and ``b`` hold the same postings and lengths."""
    return a.postings == b.postings and a.lengths == b.lengths
