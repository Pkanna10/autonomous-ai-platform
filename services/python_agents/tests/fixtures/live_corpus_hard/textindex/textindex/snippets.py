"""The window of a document that best shows why it matched."""

from textindex.stemmer import stem
from textindex.tokens import tokens

WINDOW = 12


def best_window(text: str, terms: list[str], width: int = WINDOW) -> tuple[int, int]:
    """Token positions ``(start, end)`` of the window holding the most query
    terms; the earliest such window."""
    words = tokens(text)
    wanted = set(terms)
    hits = [1 if stem(token.text) in wanted else 0 for token in words]
    if not words:
        return 0, 0
    width = min(width, len(words))
    current = sum(hits[:width])
    best, best_start = current, 0
    for start in range(1, len(words) - width + 1):
        current += hits[start + width - 1] - hits[start - 1]
        if current > best:
            best, best_start = current, start
    return best_start, best_start + width


def snippet(text: str, terms: list[str], width: int = WINDOW) -> str:
    """The best window as text, with matching words in brackets."""
    words = tokens(text)
    start, end = best_window(text, terms, width)
    wanted = set(terms)
    shown: list[str] = []
    for token in words[start:end]:
        original = text[token.start : token.start + len(token.text)]
        shown.append(f"[{original}]" if stem(token.text) in wanted else original)
    prefix = "... " if start > 0 else ""
    suffix = " ..." if end < len(words) else ""
    return prefix + " ".join(shown) + suffix
