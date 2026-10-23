"""A deterministic corpus: the same words on every run and platform."""

SYLLABLES = ("ka", "lo", "mi", "ne", "ru", "sa", "to", "vi")


def generate(count: int, seed: int = 7) -> list[str]:
    """Return ``count`` pseudo-random words built from ``SYLLABLES``."""
    state = seed
    words: list[str] = []
    for _ in range(count):
        state = (state * 1103515245 + 12345) % (1 << 31)
        first = SYLLABLES[state % len(SYLLABLES)]
        second = SYLLABLES[(state >> 8) % len(SYLLABLES)]
        words.append(first + second)
    return words
