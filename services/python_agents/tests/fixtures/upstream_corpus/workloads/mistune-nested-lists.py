"""OSS corpus benchmark: mistune renders a generated outline document with
the task-lists plugin: 150 top-level items, lists nested four to five
levels deep with mixed markers and indents (two and four spaces, a tab now
and then), multi-paragraph items with indented continuation lines, lazy
continuation lines, fenced code and blockquotes inside items, and loose
lists with blank lines between items; about 500 KB of markdown.

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
ITEMS = 150
WORDS = ("engine", "trial", "judge", "verdict", "noise", "branch", "profile", "cache")
MARKERS = ("-", "*", "+", "1.", "2)")


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(mistune.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"mistune imported from {mistune.__file__}, not {PACKAGE_INIT}"
        )


def _sentence(rng: random.Random) -> str:
    words = [rng.choice(WORDS) for _ in range(rng.randint(5, 12))]
    words[rng.randrange(len(words))] = f"`{rng.choice(WORDS)}`"
    words[rng.randrange(len(words))] = f"**{rng.choice(WORDS)}**"
    return " ".join(words) + "."


def _item(rng: random.Random, depth: int, out: list[str]) -> None:
    unit = "\t" if rng.random() < 0.1 else " " * rng.choice((2, 4))
    indent = unit * depth
    marker = rng.choice(MARKERS)
    task = "[x] " if rng.random() < 0.3 else "[ ] " if rng.random() < 0.3 else ""
    out.append(f"{indent}{marker} {task}{_sentence(rng)}")
    body = indent + " " * (len(marker) + 1)
    shape = rng.randrange(8)
    if shape == 0:
        out.append(f"{body}{_sentence(rng)}")  # indented continuation line
    elif shape == 1:
        out.append(_sentence(rng))  # lazy continuation line
    elif shape == 2:
        out.append("")
        out.append(f"{body}{_sentence(rng)}")  # a second paragraph in the item
    elif shape == 3:
        out.append("")
        out.append(f"{body}```python\n{body}value = {depth}\n{body}```")
    elif shape == 4:
        out.append("")
        out.append(f"{body}> {_sentence(rng)}")
    if depth < 5 and rng.random() < 0.8:
        if rng.random() < 0.25:
            out.append("")  # a loose nested list
        for _ in range(rng.randint(1, 3)):
            _item(rng, depth + 1, out)


def _document(rng: random.Random) -> str:
    lines: list[str] = []
    for n in range(ITEMS):
        if n % 10 == 0:
            lines.append(f"## Outline {n // 10}")
            lines.append("")
            lines.append(_sentence(rng))
            lines.append("")
        _item(rng, 0, lines)
        if n % 3 == 0:
            lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    _checked()
    text = _document(random.Random(5))
    render = mistune.create_markdown(plugins=["task_lists"])
    html = render(text)
    assert isinstance(html, str)
    digest = hashlib.sha256(html.encode()).hexdigest()
    print(f"mistune bytes_in={len(text)} bytes_out={len(html)} sha256={digest}")


if __name__ == "__main__":
    main()
