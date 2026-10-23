"""Counting climbs."""

MOVES = (1, 3, 4)


def ways(height: int) -> int:
    """The number of move sequences from ``MOVES`` that climb exactly ``height``."""
    if height < 0:
        return 0
    if height == 0:
        return 1
    return sum(ways(height - move) for move in MOVES)
