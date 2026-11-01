"""OSS corpus benchmark: Python-Markdown converts a generated API reference
(700 entries, each with the same three sub-headings: Parameters, Returns,
Examples; about 3,000 headings of levels 2 to 4 with a short paragraph under
each and a ``[TOC]`` marker at the top) with the Table of Contents extension
and permalinks, as a documentation site does.

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
ENTRIES = 700
WORDS = ("engine", "trial", "judge", "verdict", "noise", "branch", "profile", "cache")
SUBSECTIONS = ("Parameters", "Returns", "Examples")


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(markdown.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"markdown imported from {markdown.__file__}, not {PACKAGE_INIT}"
        )


def _sentence(rng: random.Random) -> str:
    words = [rng.choice(WORDS) for _ in range(rng.randint(6, 12))]
    words[rng.randrange(len(words))] = f"`{rng.choice(WORDS)}`"
    words[rng.randrange(len(words))] = f"*{rng.choice(WORDS)}*"
    return " ".join(words) + "."


def _document(rng: random.Random) -> str:
    parts = ["# Reference\n", "[TOC]\n"]
    for n in range(ENTRIES):
        name = rng.choice(WORDS).title() + rng.choice(
            ("Loader", "Runner", "Judge", "Store")
        )
        if n % 5 == 0:
            parts.append(f"## `{name}` ({n})\n")  # inline code in the heading
        elif n % 5 == 1:
            parts.append(f"## {name} &amp; friends\n")  # an entity in the heading
        else:
            parts.append(f"## {name}\n")
        parts.append(_sentence(rng) + "\n")
        for sub in SUBSECTIONS:
            parts.append(f"### {sub}\n")
            parts.append(_sentence(rng) + "\n")
            if n % 9 == 0:
                parts.append(f"#### [{rng.choice(WORDS)}](#{sub.lower()})\n")
                parts.append(_sentence(rng) + "\n")
    return "\n".join(parts)


def main() -> None:
    _checked()
    text = _document(random.Random(31))
    md = markdown.Markdown(
        extensions=["markdown.extensions.toc"],
        extension_configs={
            "markdown.extensions.toc": {"permalink": True, "toc_depth": "2-3"}
        },
    )
    html = md.convert(text)
    digest = hashlib.sha256(html.encode())
    digest.update(md.toc.encode())
    print(
        f"markdown bytes_in={len(text)} bytes_out={len(html)} "
        f"toc_bytes={len(md.toc)} sha256={digest.hexdigest()}"
    )


if __name__ == "__main__":
    main()
