"""OSS corpus benchmark: boltons rewrites a generated 500 KB text with four
multi-replace tables, the way a templating or redaction pass does: 80 plain
words from a dict, an ordered list of 40 pairs whose keys overlap, 25
regular-expression patterns with ``IGNORECASE``, and the ``multi_replace``
shortcut on a 100 KB slice; about 50,000 matches over the four passes.

Copied into the cloned repository as ``benchmarks/bench_boltons.py``.
Deterministic: a fixed seed, no clock, no network; prints a digest.
"""

from __future__ import annotations

import hashlib
import random
import re
from pathlib import Path

import boltons
from boltons.strutils import MultiReplace, multi_replace

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "boltons" / "__init__.py"
WORDS = 300
TEXT_WORDS = 50000
PLAIN = 80
ORDERED = 40
PATTERNS = 25


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(boltons.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"boltons imported from {boltons.__file__}, not {PACKAGE_INIT}"
        )


def _vocabulary(rng: random.Random) -> list[str]:
    syllables = (
        "en",
        "gi",
        "ne",
        "tri",
        "al",
        "ju",
        "dge",
        "ver",
        "dict",
        "no",
        "ise",
        "bra",
        "nch",
        "pro",
        "file",
        "ca",
        "che",
    )
    return [
        "".join(rng.choice(syllables) for _ in range(rng.randint(2, 4))) + str(k % 10)
        for k in range(WORDS)
    ]


def _text(rng: random.Random, vocabulary: list[str]) -> str:
    words = []
    for k in range(TEXT_WORDS):
        word = rng.choice(vocabulary)
        if k % 11 == 0:
            word = word.capitalize()
        if k % 17 == 0:
            word = f"{word}, "
        elif k % 23 == 0:
            word = f"{word}.\n"
        else:
            word += " "
        words.append(word)
    return "".join(words)


def main() -> None:
    _checked()
    rng = random.Random(97)
    vocabulary = _vocabulary(rng)
    text = _text(rng, vocabulary)
    digest = hashlib.sha256()

    plain = MultiReplace({word: f"<{word.upper()}>" for word in vocabulary[:PLAIN]})
    rewritten = plain.sub(text)
    digest.update(rewritten.encode())

    pairs = [
        (word, vocabulary[(k + 7) % WORDS])
        for k, word in enumerate(vocabulary[50 : 50 + ORDERED])
    ]
    pairs += [
        (word[:3], "***") for word in vocabulary[:5]
    ]  # overlapping shorter keys, later
    ordered = MultiReplace(pairs)
    digest.update(ordered.sub(text).encode())

    patterns = [
        (rf"\b{word[:4]}\w*", f"[{k}]")
        for k, word in enumerate(vocabulary[100 : 100 + PATTERNS - 3])
    ]
    patterns += [(r"\d+", "#"), (r"[A-Z][a-z]+", "Name"), (re.compile(r",\s+"), "; ")]
    regex = MultiReplace(patterns, regex=True, flags=re.IGNORECASE)
    digest.update(regex.sub(text).encode())

    digest.update(
        multi_replace(text[:100_000], {"a": "4", "e": "3", ". ": ".  "}).encode()
    )
    print(
        f"boltons bytes={len(text)} rewritten={len(rewritten)} sha256={digest.hexdigest()}"
    )


if __name__ == "__main__":
    main()
