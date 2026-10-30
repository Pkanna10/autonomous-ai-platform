"""OSS corpus benchmark: Python-Markdown converts a generated 800-paragraph
technical document to HTML. Its prose is dense in inline markup (emphasis,
strong, code spans, links, images, autolinks, entities, escapes, raw inline
HTML) and in characters that look like markup but are not (identifiers with
underscores, products with asterisks, bracketed citations without a link,
lone backticks); every eighth paragraph is a long "see also" or changelog
block holding 60 to 150 inline links, code spans and emphasised names in
one paragraph, as release notes and index pages do.

Copied into the cloned repository as ``benchmarks/bench_markdown.py``.
Deterministic: a fixed seed, no clock, no network; prints a digest.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "markdown" / "__init__.py"
PARAGRAPHS = 800
WORDS = ("engine", "trial", "judge", "verdict", "noise", "branch", "profile", "cache")
IDENTIFIERS = ("run_loop", "max_cost_usd", "__init__", "snake_case_name", "a_b_c")
LOOKALIKES = (
    "2 * 3 * 4",
    "[citation needed]",
    "[12]",
    "x_1 and x_2",
    "a lone ` backtick",
    "5 < 6 > 4",
    "AT&T",
    "100% * 2",
    "see [the docs] (later)",
    "_not emphasis",
    "**",
    "C# and F#",
)


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(markdown.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"markdown imported from {markdown.__file__}, not {PACKAGE_INIT}"
        )


def _sentence(rng: random.Random) -> str:
    words = [rng.choice(WORDS) for _ in range(rng.randint(6, 14))]
    for _ in range(rng.randint(1, 4)):
        kind = rng.randrange(9)
        slot = rng.randrange(len(words))
        word = rng.choice(WORDS)
        if kind == 0:
            words[slot] = f"*{word}*"
        elif kind == 1:
            words[slot] = f"**{word}**"
        elif kind == 2:
            words[slot] = f"`{rng.choice(IDENTIFIERS)}()`"
        elif kind == 3:
            words[slot] = f"[{word}](https://example.org/{rng.randrange(999)})"
        elif kind == 4:
            words[slot] = f"<https://example.org/{word}/{rng.randrange(99)}>"
        elif kind == 5:
            words[slot] = rng.choice(IDENTIFIERS)
        elif kind == 6:
            words[slot] = rng.choice(LOOKALIKES)
        elif kind == 7:
            words[slot] = rng.choice(
                ("&copy;", "&amp;", "\\*literal\\*", "<kbd>Ctrl</kbd>")
            )
        else:
            words[slot] = f"![{word}](img/{rng.randrange(50)}.png)"
    return " ".join(words) + rng.choice((".", "!", "?", "..."))


def _reference_block(rng: random.Random, n: int) -> str:
    """One long paragraph of links, code spans and names: a "see also" list
    or a changelog entry written as running text."""
    items = []
    for k in range(rng.randint(60, 150)):
        word = rng.choice(WORDS)
        kind = k % 4
        if kind == 0:
            items.append(f"[{word} {k}](https://example.org/{n}/{word}/{k})")
        elif kind == 1:
            items.append(f"`{rng.choice(IDENTIFIERS)}.{word}`")
        elif kind == 2:
            items.append(f"*{word}* ({rng.randint(1, 99)})")
        else:
            items.append(
                f"**{word}** fixed in [#{rng.randrange(9999)}](https://example.org/issues/{k})"
            )
    return "See also: " + ", ".join(items) + "."


def _document(rng: random.Random) -> str:
    parts: list[str] = []
    for n in range(PARAGRAPHS):
        if n % 12 == 0:
            parts.append(f"## Section {n // 12}\n")
        if n % 8 == 7:
            parts.append(_reference_block(rng, n) + "\n")
            continue
        parts.append(" ".join(_sentence(rng) for _ in range(rng.randint(2, 5))) + "\n")
        if n % 7 == 0:
            parts.append(f"* {_sentence(rng)}\n* {_sentence(rng)}\n")
    return "\n".join(parts)


def main() -> None:
    _checked()
    text = _document(random.Random(29))
    html = markdown.markdown(text)
    digest = hashlib.sha256(html.encode()).hexdigest()
    print(f"markdown bytes_in={len(text)} bytes_out={len(html)} sha256={digest}")


if __name__ == "__main__":
    main()
