"""Distances along the round."""

from deliveryround.network import Stop


def leg_length(a: Stop, b: Stop) -> int:
    """Manhattan distance between two stops, in metres."""
    return abs(a.x - b.x) + abs(a.y - b.y)


def distance_so_far(lengths: list[int]) -> list[int]:
    """For each leg, the distance driven before it starts."""
    return [sum(lengths[:i]) for i in range(len(lengths))]
