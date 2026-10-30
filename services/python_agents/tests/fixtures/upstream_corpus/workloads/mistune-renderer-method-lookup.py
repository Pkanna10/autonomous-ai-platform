"""OSS corpus benchmark: mistune renders a generated 450-section document
that uses eleven plugins at once (tables, strikethrough, mark, insert,
superscript, subscript, footnotes, task lists, definition lists,
abbreviations, math) with the HTML renderer; about 370 KB of markdown.

Copied into the cloned repository as ``benchmarks/bench_mistune.py``.
Deterministic: a fixed seed, no clock, no network; prints a digest.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import mistune

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "src" / "mistune" / "__init__.py"
SECTIONS = 450
WORDS = ("engine", "trial", "judge", "verdict", "noise", "branch", "profile", "cache")
PLUGINS = (
    "table",
    "strikethrough",
    "mark",
    "insert",
    "superscript",
    "subscript",
    "footnotes",
    "task_lists",
    "def_list",
    "abbr",
    "math",
)


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(mistune.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"mistune imported from {mistune.__file__}, not {PACKAGE_INIT}"
        )


def _sentence(rng: random.Random) -> str:
    words = [rng.choice(WORDS) for _ in range(rng.randint(6, 14))]
    for _ in range(rng.randint(2, 5)):
        slot = rng.randrange(len(words))
        word = rng.choice(WORDS)
        words[slot] = rng.choice(
            (
                f"*{word}*",
                f"**{word}**",
                f"`{word}`",
                f"~~{word}~~",
                f"=={word}==",
                f"^^{word}^^",
                f"^{word}^",
                f"~{word}~",
                f"${word}_i$",
                f"[{word}](https://example.org/{rng.randrange(99)})",
                "HTML",
            )
        )
    return " ".join(words) + "."


def _document(rng: random.Random) -> str:
    parts = ["*[HTML]: Hyper Text Markup Language\n"]
    for n in range(SECTIONS):
        parts.append(f"{'#' * rng.randint(1, 3)} Section {n}\n")
        parts.append(" ".join(_sentence(rng) for _ in range(3)) + f"[^n{n}]\n")
        parts.append(
            "".join(f"- [{'x' if k % 2 else ' '}] {_sentence(rng)}\n" for k in range(3))
        )
        if n % 2 == 0:
            rows = "".join(
                f"| {r} | {rng.choice(WORDS)} | ~~{rng.choice(WORDS)}~~ | =={r * n}== |\n"
                for r in range(4)
            )
            parts.append(
                f"| id | word | gone | mark |\n| --- | --- | --- | ---: |\n{rows}"
            )
        if n % 3 == 0:
            parts.append(f"Term {n}\n: {_sentence(rng)}\n: {_sentence(rng)}\n")
        if n % 4 == 0:
            parts.append(f"$$\n\\sum_{{i=0}}^{{{n}}} x_i^2\n$$\n")
        if n % 5 == 0:
            parts.append(f"> {_sentence(rng)}\n")
        parts.append(f"[^n{n}]: {_sentence(rng)}\n")
    return "\n".join(parts)


def main() -> None:
    _checked()
    text = _document(random.Random(7))
    render = mistune.create_markdown(plugins=list(PLUGINS))
    html = render(text)
    assert isinstance(html, str)
    digest = hashlib.sha256(html.encode()).hexdigest()
    print(f"mistune bytes_in={len(text)} bytes_out={len(html)} sha256={digest}")


if __name__ == "__main__":
    main()
