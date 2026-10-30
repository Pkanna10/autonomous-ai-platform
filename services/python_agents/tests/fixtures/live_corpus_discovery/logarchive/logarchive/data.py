"""A deterministic day of log text: the same bytes on every run."""

import random

SYLLABLES = (b"ka", b"lo", b"mi", b"ne", b"ru", b"sa", b"to", b"vi")
WORDS = tuple(
    SYLLABLES[n % 8] + SYLLABLES[n // 8 % 8] + SYLLABLES[n // 64] for n in range(256)
)


def day_log(words: int) -> bytes:
    """``words`` words drawn from ``WORDS``, separated by spaces."""
    return b" ".join(map(WORDS.__getitem__, random.Random(5).randbytes(words)))
