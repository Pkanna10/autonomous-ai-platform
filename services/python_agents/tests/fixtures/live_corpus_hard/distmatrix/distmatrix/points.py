"""Deterministic survey points: the same set on every run."""


def generate(count: int, seed: int = 61) -> list[tuple[float, float]]:
    """``count`` points in a 1000 x 1000 square."""
    state = seed
    out: list[tuple[float, float]] = []
    for _ in range(count):
        state = (state * 1103515245 + 12345) % (1 << 31)
        x = (state >> 4) % 100000 / 100
        state = (state * 1103515245 + 12345) % (1 << 31)
        y = (state >> 4) % 100000 / 100
        out.append((x, y))
    return out
