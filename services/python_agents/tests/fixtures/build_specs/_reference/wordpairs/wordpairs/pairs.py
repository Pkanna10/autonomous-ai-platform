import re

STOP = frozenset("a an and in is it of on the to was with".split())
WORD = re.compile(r"[A-Za-z]+")


def _counts(text: str) -> dict:
    words = [w.lower() for w in WORD.findall(text)]
    counts = {}
    for first, second in zip(words, words[1:], strict=False):
        if first in STOP or second in STOP:
            continue
        counts[(first, second)] = counts.get((first, second), 0) + 1
    return counts


def _ordered(counts: dict) -> list:
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def top_pairs(text: str, n: int = 20) -> list:
    if n < 1:
        raise ValueError("n must be at least 1")
    return [(a, b, c) for (a, b), c in _ordered(_counts(text))[:n]]


def render(text: str, n: int = 20) -> str:
    if n < 1:
        raise ValueError("n must be at least 1")
    counts = _counts(text)
    lines = [
        f"{rank}\t{a} {b}\t{c}"
        for rank, ((a, b), c) in enumerate(_ordered(counts)[:n], start=1)
    ]
    lines.append(f"kept={sum(counts.values())} distinct={len(counts)}")
    return "\n".join(lines) + "\n"
