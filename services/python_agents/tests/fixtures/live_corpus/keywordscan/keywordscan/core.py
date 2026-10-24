"""Keyword matching on log lines."""

import re


def mentions(text: str, keywords: list[str]) -> bool:
    """True when ``text`` contains any of ``keywords`` as a whole word."""
    alternatives = "|".join(re.escape(word) for word in sorted(set(keywords)))
    pattern = re.compile(rf"\b(?:{alternatives})\b")
    return pattern.search(text) is not None


def hits_by_level(lines: list[tuple[str, str]], keywords: list[str]) -> dict[str, int]:
    """How many lines of each level mention a keyword, levels sorted."""
    hits: dict[str, int] = {}
    for level, text in lines:
        hits.setdefault(level, 0)
        if mentions(text, keywords):
            hits[level] += 1
    return dict(sorted(hits.items()))
