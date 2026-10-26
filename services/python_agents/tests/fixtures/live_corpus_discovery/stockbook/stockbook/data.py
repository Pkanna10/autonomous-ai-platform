"""Deterministic stock movements: the same lines on every run."""


def movements(count: int, codes: int) -> list[str]:
    """``count`` movement lines ``kind|code|quantity``: kind ``R`` receives
    stock, ``S`` ships it."""
    state = 41
    lines: list[str] = []
    for _ in range(count):
        state = (state * 1103515245 + 12345) % (1 << 31)
        kind = "R" if state % 5 < 2 else "S"
        lines.append(f"{kind}|SKU-{(state >> 8) % codes:05d}|{(state >> 3) % 40 + 1}")
    return lines
