"""Deterministic sensor readings: the same values on every run."""


def _numbers(seed: int, count: int) -> list[int]:
    state = seed
    out: list[int] = []
    for _ in range(count):
        state = (state * 1103515245 + 12345) % (1 << 31)
        out.append(state >> 4)
    return out


def series(sensor: int, count: int) -> list[float]:
    """``count`` readings of ``sensor``: a gradual drift plus jitter, with values
    that are not exact binary fractions."""
    base = 12.5 + sensor * 3.7
    jitter = _numbers(1000 + sensor, count)
    return [
        base + (i % 97) * 0.013 + (n % 10007) / 3333.0 - 1.5
        for i, n in enumerate(jitter)
    ]
