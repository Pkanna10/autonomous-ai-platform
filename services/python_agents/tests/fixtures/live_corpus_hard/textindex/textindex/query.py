"""Boolean queries: ``AND`` (the default), ``OR``, ``NOT`` and "phrases"."""

from dataclasses import dataclass

from textindex.index import Index, index_terms


@dataclass(frozen=True)
class Clause:
    terms: tuple[str, ...]  # one term, or a phrase of several
    negated: bool = False

    @property
    def is_phrase(self) -> bool:
        return len(self.terms) > 1


@dataclass(frozen=True)
class Query:
    groups: tuple[tuple[Clause, ...], ...]  # OR of ANDs


def _split(text: str) -> list[str]:
    parts: list[str] = []
    quoted = False
    current = ""
    for ch in text:
        if ch == '"':
            if quoted:
                parts.append('"' + current)
                current = ""
            quoted = not quoted
        elif ch == " " and not quoted:
            if current:
                parts.append(current)
            current = ""
        else:
            current += ch
    if quoted:
        raise ValueError("unclosed quote")
    if current:
        parts.append(current)
    return parts


def parse(text: str) -> Query:
    groups: list[tuple[Clause, ...]] = []
    current: list[Clause] = []
    negate = False
    for part in _split(text):
        if part == "OR":
            if current:
                groups.append(tuple(current))
            current = []
        elif part == "NOT":
            negate = True
        elif part == "AND":
            continue
        else:
            words = part[1:] if part.startswith('"') else part
            terms = tuple(term for term, _ in index_terms(words))
            if terms:
                current.append(Clause(terms, negate))
            negate = False
    if current:
        groups.append(tuple(current))
    if not groups:
        raise ValueError("empty query")
    return Query(tuple(groups))


def phrase_documents(index: Index, terms: tuple[str, ...]) -> set[int]:
    """Documents holding ``terms`` at consecutive indexed positions or with
    stop words between them (positions increase)."""
    first = index.postings.get(terms[0], {})
    found: set[int] = set()
    for document, positions in first.items():
        for start in positions:
            last = start
            for term in terms[1:]:
                after = [p for p in index.positions(term, document) if p > last]
                if not after or after[0] - last > 3:
                    break
                last = after[0]
            else:
                found.add(document)
                break
    return found


def clause_documents(index: Index, clause: Clause) -> set[int]:
    if clause.is_phrase:
        return phrase_documents(index, clause.terms)
    return set(index.postings.get(clause.terms[0], {}))


def evaluate(index: Index, query: Query) -> set[int]:
    every = set(index.lengths)
    matched: set[int] = set()
    for group in query.groups:
        docs = set(every)
        for clause in group:
            hits = clause_documents(index, clause)
            docs = docs - hits if clause.negated else docs & hits
        matched |= docs
    return matched


def positive_terms(query: Query) -> list[str]:
    """The terms that count towards ranking (not negated), once each."""
    seen: dict[str, None] = {}
    for group in query.groups:
        for clause in group:
            if not clause.negated:
                for term in clause.terms:
                    seen[term] = None
    return list(seen)
