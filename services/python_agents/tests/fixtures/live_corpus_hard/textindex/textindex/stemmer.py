"""A light suffix-stripping stemmer (a few English rules, longest first)."""

SUFFIXES = (
    ("ational", "ate"),
    ("ations", "ate"),
    ("ation", "ate"),
    ("ements", ""),
    ("ement", ""),
    ("ings", ""),
    ("ing", ""),
    ("ness", ""),
    ("ies", "y"),
    ("ers", ""),
    ("er", ""),
    ("ed", ""),
    ("ly", ""),
    ("es", ""),
    ("s", ""),
)
MIN_STEM = 3


def stem(word: str) -> str:
    """``word`` with its first matching suffix replaced, keeping at least
    ``MIN_STEM`` characters; words ending in ``ss`` keep their ``s``."""
    if word.endswith("ss"):
        return word
    for suffix, replacement in SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= MIN_STEM:
            return word[: -len(suffix)] + replacement
    return word


def stems(words: list[str]) -> list[str]:
    return [stem(word) for word in words]
