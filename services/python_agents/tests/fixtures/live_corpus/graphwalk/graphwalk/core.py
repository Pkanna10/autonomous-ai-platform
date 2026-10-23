"""Breadth-first search."""


def hops(edges: list[list[int]], start: int) -> dict[int, int]:
    """Members reachable from ``start`` and their hop count."""
    distance = {start: 0}
    pending = [start]
    while pending:
        node = pending.pop(0)
        for target in edges[node]:
            if target not in distance:
                distance[target] = distance[node] + 1
                pending.append(target)
    return distance
