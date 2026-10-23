"""A deterministic text."""

SYLLABLES = ("ba", "de", "fi", "go", "hu", "ja", "ke", "li", "mo", "nu", "pa", "re")


def words(count: int, distinct: int) -> list[str]:
    """``count`` words drawn from ``distinct`` possible words."""
    state = 101
    out: list[str] = []
    for _ in range(count):
        state = (state * 1103515245 + 12345) % (1 << 31)
        n = (state >> 4) % distinct
        out.append(SYLLABLES[n % 12] + SYLLABLES[(n // 12) % 12] + str(n // 144))
    return out
