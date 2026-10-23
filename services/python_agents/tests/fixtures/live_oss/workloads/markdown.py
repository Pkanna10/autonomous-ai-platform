"""OSS corpus benchmark: Python-Markdown converts a generated 500-section
document (headings, emphasis, links, nested lists, quotes, fenced code,
tables, abbreviations) to HTML with the tables, fenced code and abbr
extensions, given as dotted import paths (no installed entry points).

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
SECTIONS = 500
WORDS = ("engine", "trial", "judge", "verdict", "noise", "branch", "profile", "HTML")
EXTENSIONS = (
    "markdown.extensions.tables",
    "markdown.extensions.fenced_code",
    "markdown.extensions.abbr",
)


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(markdown.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"markdown imported from {markdown.__file__}, not {PACKAGE_INIT}"
        )


def _sentence(rng: random.Random) -> str:
    words = [rng.choice(WORDS) for _ in range(rng.randint(6, 14))]
    words[rng.randrange(len(words))] = f"*{rng.choice(WORDS)}*"
    words[rng.randrange(len(words))] = f"__{rng.choice(WORDS)}__"
    words[rng.randrange(len(words))] = f"`{rng.choice(WORDS)}()`"
    words[rng.randrange(len(words))] = (
        f"[{rng.choice(WORDS)}](https://example.org/{rng.randrange(999)})"
    )
    return " ".join(words) + " & more."


def _document(rng: random.Random) -> str:
    parts = ["*[HTML]: Hyper Text Markup Language\n"]
    for n in range(SECTIONS):
        parts.append(f"{'#' * rng.randint(1, 4)} Section {n}\n")
        parts.append(" ".join(_sentence(rng) for _ in range(3)) + "\n")
        parts.append(
            "".join(f"* {_sentence(rng)}\n    1. {_sentence(rng)}\n" for _ in range(2))
        )
        if n % 3 == 0:
            parts.append(f"> {_sentence(rng)}\n> {_sentence(rng)}\n")
        if n % 4 == 0:
            parts.append(f"```python\nvalue_{n} = {n} * 2\nprint(value_{n})\n```\n")
        if n % 5 == 0:
            rows = "".join(
                f"| {r} | {rng.choice(WORDS)} | {rng.random():.3f} |\n"
                for r in range(4)
            )
            parts.append(f"| id | word | score |\n| --- | --- | ---: |\n{rows}")
    return "\n".join(parts)


def main() -> None:
    _checked()
    text = _document(random.Random(29))
    html = markdown.markdown(text, extensions=list(EXTENSIONS))
    digest = hashlib.sha256(html.encode()).hexdigest()
    print(f"markdown bytes_in={len(text)} bytes_out={len(html)} sha256={digest}")


if __name__ == "__main__":
    main()
