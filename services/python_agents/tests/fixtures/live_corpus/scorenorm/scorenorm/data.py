"""Deterministic exam scores."""


def scores(count: int) -> list[float]:
    """``count`` scores between 0 and 100, with two decimals."""
    state = 9
    out: list[float] = []
    for _ in range(count):
        state = (state * 1103515245 + 12345) % (1 << 31)
        out.append((state % 10001) / 100)
    return out
