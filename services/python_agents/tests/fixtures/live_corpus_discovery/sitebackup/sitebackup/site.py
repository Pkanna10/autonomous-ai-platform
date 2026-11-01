"""The pages of the site, rendered from a template."""

import random

SECTIONS = ("news", "guides", "events", "shop", "about")
WORDS = tuple(
    first + middle + last
    for first in ("bra", "cle", "dro", "fen", "gal", "hur", "kim", "lor")
    for middle in ("a", "e", "i", "o")
    for last in ("ba", "den", "fi", "go", "lan", "mor", "ne", "sat")
)


def page(section: str, number: int, rng: random.Random) -> str:
    """One page: a title and ten paragraphs of generated text."""
    html = f"<h1>{section} {number}</h1>\n"
    for _ in range(10):
        html += "<p>" + " ".join(map(WORDS.__getitem__, rng.randbytes(24))) + "</p>\n"
    return html


def render(pages: int) -> dict[str, list[str]]:
    """``pages`` pages per section, in order."""
    rng = random.Random(13)
    return {s: [page(s, n, rng) for n in range(pages)] for s in SECTIONS}
