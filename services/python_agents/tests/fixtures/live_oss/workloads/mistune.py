"""OSS corpus benchmark: mistune renders a generated 700-section markdown
document (headings, emphasis, links, inline code, nested lists, quotes,
fenced code, tables, strikethrough, footnotes) to HTML.

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
SECTIONS = 700
WORDS = ("engine", "trial", "judge", "verdict", "noise", "branch", "profile", "cache")


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(mistune.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"mistune imported from {mistune.__file__}, not {PACKAGE_INIT}"
        )


def _sentence(rng: random.Random) -> str:
    words = [rng.choice(WORDS) for _ in range(rng.randint(6, 14))]
    words[rng.randrange(len(words))] = f"*{rng.choice(WORDS)}*"
    words[rng.randrange(len(words))] = f"**{rng.choice(WORDS)}**"
    words[rng.randrange(len(words))] = f"`{rng.choice(WORDS)}()`"
    words[rng.randrange(len(words))] = (
        f"[{rng.choice(WORDS)}](https://example.org/{rng.randrange(999)})"
    )
    words[rng.randrange(len(words))] = f"~~{rng.choice(WORDS)}~~"
    return " ".join(words) + "."


def _document(rng: random.Random) -> str:
    parts: list[str] = []
    for n in range(SECTIONS):
        parts.append(f"{'#' * rng.randint(1, 4)} Section {n}\n")
        parts.append(" ".join(_sentence(rng) for _ in range(3)) + f"[^n{n}]\n")
        parts.append(
            "".join(f"- {_sentence(rng)}\n  - {_sentence(rng)}\n" for _ in range(2))
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
        parts.append(f"[^n{n}]: {_sentence(rng)}\n")
    return "\n".join(parts)


def main() -> None:
    _checked()
    text = _document(random.Random(5))
    render = mistune.create_markdown(plugins=["table", "strikethrough", "footnotes"])
    html = render(text)
    assert isinstance(html, str)
    digest = hashlib.sha256(html.encode()).hexdigest()
    print(f"mistune bytes_in={len(text)} bytes_out={len(html)} sha256={digest}")


if __name__ == "__main__":
    main()
