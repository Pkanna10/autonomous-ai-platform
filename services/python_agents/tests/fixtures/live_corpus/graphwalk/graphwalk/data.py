"""A deterministic graph: adjacency lists."""


def graph(nodes: int, degree: int) -> list[list[int]]:
    """``nodes`` members, each following ``degree`` others."""
    state = 1
    edges: list[list[int]] = []
    for _ in range(nodes):
        targets: list[int] = []
        for _ in range(degree):
            state = (state * 1103515245 + 12345) % (1 << 31)
            targets.append((state >> 3) % nodes)
        edges.append(targets)
    return edges
