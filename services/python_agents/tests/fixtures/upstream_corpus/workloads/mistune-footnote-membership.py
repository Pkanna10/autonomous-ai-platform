"""OSS corpus benchmark: mistune renders a generated annotated legal code
with the footnotes plugin: 2,200 paragraphs of short clauses, each clause
carrying a footnote reference (about 24,000 references to 10,000 footnote
definitions; most notes are cited two or three times, a few references point
at notes that do not exist), followed by the definitions, as a statute
commentary or an annotated edition does.

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
NOTES = 10000
PARAGRAPHS = 2200
WORDS = ("engine", "trial", "judge", "verdict", "noise", "branch", "profile", "cache")


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(mistune.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"mistune imported from {mistune.__file__}, not {PACKAGE_INIT}"
        )


def _clause(rng: random.Random) -> str:
    words = [rng.choice(WORDS) for _ in range(rng.randint(3, 7))]
    if rng.random() < 0.3:
        words[rng.randrange(len(words))] = f"*{rng.choice(WORDS)}*"
    return " ".join(words) + rng.choice((".", ";", ","))


def _document(rng: random.Random) -> str:
    keys = [f"n{k}" for k in range(NOTES)]
    parts: list[str] = []
    for n in range(PARAGRAPHS):
        if n % 40 == 0:
            parts.append(f"## Title {n // 40}\n")
        clauses = []
        for _ in range(rng.randint(6, 16)):
            clause = _clause(rng)
            if rng.random() < 0.97:
                key = rng.choice(keys)
            else:
                key = f"missing{rng.randrange(50)}"
            clauses.append(f"{clause}[^{key}]")
        parts.append(" ".join(clauses) + "\n")
    for key in keys:
        parts.append(f"[^{key}]: {_clause(rng)}\n")
    return "\n".join(parts)


def main() -> None:
    _checked()
    text = _document(random.Random(11))
    render = mistune.create_markdown(plugins=["footnotes"])
    html = render(text)
    assert isinstance(html, str)
    digest = hashlib.sha256(html.encode()).hexdigest()
    print(f"mistune bytes_in={len(text)} bytes_out={len(html)} sha256={digest}")


if __name__ == "__main__":
    main()
