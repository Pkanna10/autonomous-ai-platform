"""OSS corpus benchmark: markdown-it-py renders a generated 1,500-paragraph
CommonMark document with inline HTML enabled, tables and strikethrough. The
prose is dense in inline markup and in punctuation (dashes, colons, at-signs,
braces, tildes, percent signs, ampersands, angle brackets); every twenty-fifth
paragraph is a pasted log or request dump, one line of 4,000 to 12,000
characters full of query strings, angle brackets and tildes, and every
fortieth paragraph is a table whose cells hold such dumps, as issue trackers
and incident reports do.

Copied into the cloned repository as ``benchmarks/bench_markdown_it.py``.
Deterministic: a fixed seed, no clock, no network; prints a digest.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import markdown_it
from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "markdown_it" / "__init__.py"
PARAGRAPHS = 1500
WORDS = ("engine", "trial", "judge", "verdict", "noise", "branch", "profile", "cache")
PUNCTUATED = (
    "well-known",
    "key: value",
    "@maintainer",
    "#1234",
    "{braces}",
    "~tilde",
    "50% done",
    "a + b = c",
    "x ^ 2",
    "$price",
    "dash - dash",
    "wait...",
    "3 < 4 > 2",
    "slash\\back",
    "end!",
)
ENTITIES = (
    "&amp;",
    "&copy;",
    "&hellip;",
    "&#169;",
    "&#x1F600;",
    "&nbsp;",
    "&notanentity;",
    "&#;",
    "& loose",
)
HTML = (
    "<b>bold</b>",
    '<span class="x">s</span>',
    "<!-- note -->",
    "<br/>",
    "<?pi ?>",
    "<3 fail",
    "< not a tag",
    "</em>",
)
LOG_FIELDS = (
    "GET /api/v1/{w}?page={n}&sort=asc&filter=a<b&q={w}%20{w} <- 200 ~{n}ms",
    "POST /hooks/{w} payload={{id:{n},kind:{w}}} <= 202 ~{n}ms",
    "[{w}@{n}] warn: retry {n} of 5 for {w} <none> & {w}",
    "{w}={n}&{w}_id={n}&token=<redacted>&{w}~{n}",
    "trace {n}: {w} -> {w} (took ~{n} ms, 1<2, a&b)",
)


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(markdown_it.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"markdown_it imported from {markdown_it.__file__}, not {PACKAGE_INIT}"
        )


def _sentence(rng: random.Random) -> str:
    words = [rng.choice(WORDS) for _ in range(rng.randint(6, 14))]
    for _ in range(rng.randint(2, 5)):
        kind = rng.randrange(11)
        slot = rng.randrange(len(words))
        word = rng.choice(WORDS)
        if kind == 0:
            words[slot] = f"*{word}*"
        elif kind == 1:
            words[slot] = f"**{word}**"
        elif kind == 2:
            words[slot] = f"`{word}()`"
        elif kind == 3:
            words[slot] = "`` ` ``" if rng.random() < 0.5 else "lone ` tick"
        elif kind == 4:
            words[slot] = f"[{word}](https://example.org/{rng.randrange(999)})"
        elif kind == 5:
            words[slot] = f"<https://example.org/{word}>"
        elif kind == 6:
            words[slot] = rng.choice(ENTITIES)
        elif kind == 7:
            words[slot] = rng.choice(HTML)
        elif kind == 8:
            words[slot] = rng.choice(PUNCTUATED)
        elif kind == 9:
            words[slot] = f"~~{word}~~"
        else:
            words[slot] = f"\\*{word}\\_"
    return " ".join(words) + rng.choice((".", "!", "?", "  \n"))


def _dump(rng: random.Random, length: int) -> str:
    """One line of pasted log output, ``length`` characters or a little more."""
    pieces = []
    size = 0
    while size < length:
        piece = rng.choice(LOG_FIELDS).format(
            w=rng.choice(WORDS), n=rng.randint(1, 999)
        )
        pieces.append(piece)
        size += len(piece) + 1
    return " ".join(pieces)


def _document(rng: random.Random) -> str:
    parts: list[str] = []
    for n in range(PARAGRAPHS):
        if n % 20 == 0:
            parts.append(f"## Section {n // 20}\n")
        if n % 25 == 24:
            parts.append(_dump(rng, rng.randint(4000, 12000)) + "\n")
            continue
        parts.append(" ".join(_sentence(rng) for _ in range(rng.randint(2, 4))) + "\n")
        if n % 15 == 0:
            parts.append(f"- {_sentence(rng)}\n- {_sentence(rng)}\n")
        if n % 40 == 0:
            rows = "".join(
                f"| {r} | {_sentence(rng)} | {_dump(rng, rng.randint(300, 1500))} |\n"
                for r in range(3)
            )
            parts.append(f"| id | text | log |\n| --- | --- | --- |\n{rows}")
    return "\n".join(parts)


def main() -> None:
    _checked()
    text = _document(random.Random(41))
    md = MarkdownIt("commonmark", {"html": True}).enable(["table", "strikethrough"])
    html = md.render(text)
    digest = hashlib.sha256(html.encode()).hexdigest()
    print(f"markdown_it bytes_in={len(text)} bytes_out={len(html)} sha256={digest}")


if __name__ == "__main__":
    main()
