"""Tallying tokens."""


def tally(text: str) -> tuple[int, int, int]:
    """``(words, integers, sum of integers)`` of the tokens in ``text``."""
    words = integers = total = 0
    for token in text.split():
        try:
            value = int(token)
        except ValueError:
            words += 1
            continue
        integers += 1
        total += value
    return words, integers, total
