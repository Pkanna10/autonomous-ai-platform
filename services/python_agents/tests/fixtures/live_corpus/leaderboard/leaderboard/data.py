"""A deterministic stream of game results."""


def results(count: int, players: int) -> list[tuple[str, int]]:
    """``count`` results of ``(player, points)``."""
    state = 13
    out: list[tuple[str, int]] = []
    for _ in range(count):
        state = (state * 1103515245 + 12345) % (1 << 31)
        out.append((f"p{state % players:04d}", (state >> 8) % 100000))
    return out
