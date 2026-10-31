"""OSS corpus benchmark: Python-Markdown converts a generated 900-section
document assembled from engineering notes whose headings are written every
way real authors write them: one to six hashes, closing hashes, trailing
spaces, escaped hashes, no space after the hashes, a heading glued to the
paragraph before or after it, headings inside blockquotes and list items,
comment-style banner headings copied from shell and Python scripts
(``# ##### Title #####``, 40 to 320 hashes wide), bare comment banners
pasted as text, and paragraphs that mention ``#123`` issue numbers and
``C#`` mid-line.

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
SECTIONS = 900
WORDS = ("engine", "trial", "judge", "verdict", "noise", "branch", "profile", "cache")
BANNER_WIDTHS = (40, 60, 72, 80, 80, 100, 120, 160, 200, 240, 320)


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(markdown.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"markdown imported from {markdown.__file__}, not {PACKAGE_INIT}"
        )


def _sentence(rng: random.Random) -> str:
    words = [rng.choice(WORDS) for _ in range(rng.randint(8, 16))]
    slot = rng.randrange(len(words))
    words[slot] = rng.choice(
        (
            f"#{rng.randrange(1000)}",
            "C#",
            "#hashtag",
            f"*{rng.choice(WORDS)}*",
            "issue #12",
        )
    )
    return " ".join(words) + "."


def _paragraph(rng: random.Random) -> str:
    return "\n".join(_sentence(rng) for _ in range(rng.randint(2, 7)))


def _heading(rng: random.Random, n: int) -> str:
    level = "#" * rng.randint(1, 6)
    title = f"{rng.choice(WORDS).title()} {n}"
    banner = "#" * rng.choice(BANNER_WIDTHS)
    shape = n % 12
    if shape == 0:
        return f"{level} {title} {level}"  # closing hashes
    if shape == 1:
        return f"{level} {title}   "  # trailing spaces
    if shape == 2:
        return f"{level} {title} \\#{n}"  # an escaped hash in the text
    if shape == 3:
        return f"{level}{title}"  # no space after the hashes
    if shape in (6, 7, 8, 9):
        return f"{level} {banner} {title} {banner}"  # a script-style banner heading
    if shape == 10:
        return f"{banner} {title} {banner}"  # a comment banner pasted as text
    if shape == 11:
        return f"{level} {title} {banner}"  # a long closing run
    return f"{level} {title}"


def _document(rng: random.Random) -> str:
    parts: list[str] = []
    for n in range(SECTIONS):
        heading = _heading(rng, n)
        if n % 4 == 0:
            # Heading glued to the previous paragraph and to the next one.
            parts.append(f"{_paragraph(rng)}\n{heading}\n{_paragraph(rng)}\n")
        elif n % 4 == 1:
            parts.append(f"{heading}\n\n{_paragraph(rng)}\n")
            parts.append(f"> {heading}\n> {_sentence(rng)}\n")
        elif n % 4 == 2:
            parts.append(f"{heading}\n\n{_paragraph(rng)}\n")
            parts.append(
                f"* item one\n\n    {heading}\n\n    {_sentence(rng)}\n* item two\n"
            )
        else:
            parts.append(f"{heading}\n\n{_paragraph(rng)}\n\n{_paragraph(rng)}\n")
    return "\n".join(parts)


def main() -> None:
    _checked()
    text = _document(random.Random(23))
    html = markdown.markdown(text)
    digest = hashlib.sha256(html.encode()).hexdigest()
    print(f"markdown bytes_in={len(text)} bytes_out={len(html)} sha256={digest}")


if __name__ == "__main__":
    main()
