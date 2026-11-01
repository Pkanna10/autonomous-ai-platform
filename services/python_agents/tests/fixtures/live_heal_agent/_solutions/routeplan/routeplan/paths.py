"""Shortest distances (Dijkstra's algorithm)."""

import heapq

from routeplan.graph import RouteError


def shortest(network, start, goal):
    """The length in km of the shortest route from ``start`` to ``goal``."""
    queue = [(0.0, start)]
    done = set()
    while queue:
        distance, town = heapq.heappop(queue)
        if town == goal:
            return distance
        if town in done:
            continue
        done.add(town)
        for neighbour, km in network.neighbours(town).items():
            if neighbour not in done:
                heapq.heappush(queue, (distance + km, neighbour))
    raise RouteError(f"no route from {start!r} to {goal!r}")
