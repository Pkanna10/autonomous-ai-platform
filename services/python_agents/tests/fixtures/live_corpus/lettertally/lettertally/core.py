"""Sampling and counting words."""

import random
from collections import Counter

VOCABULARY = tuple(first + second for first in "bdfgklmnprstvz" for second in "aeiouy")


def sample(count: int, seed: int = 3) -> list[str]:
    """``count`` words drawn with replacement from ``VOCABULARY``."""
    return random.Random(seed).choices(VOCABULARY, k=count)


def top_words(words: list[str], limit: int) -> list[tuple[str, int]]:
    """The ``limit`` most frequent words; ties keep first-seen order."""
    return Counter(words).most_common(limit)
