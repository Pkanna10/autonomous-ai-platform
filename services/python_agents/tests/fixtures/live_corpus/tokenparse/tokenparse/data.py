"""A deterministic token stream: mostly words, some signed integers."""

LETTERS = "abcdefghijklmnopqrstuvwxyz"
WORDS = tuple(first + second * 2 for first in LETTERS for second in LETTERS)


def stream(count: int) -> str:
    """``count`` tokens separated by single spaces."""
    tokens: list[str] = []
    for i in range(count):
        n = (i * 2654435761) % 4294967296
        if n % 20 == 0:
            tokens.append(f"-{n >> 16}" if n & 64 else str(n >> 16))
        else:
            tokens.append(WORDS[n % 676])
    return " ".join(tokens)
