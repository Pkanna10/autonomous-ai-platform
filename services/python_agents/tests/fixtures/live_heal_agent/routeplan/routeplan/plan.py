"""Tours through several stops."""

from routeplan.paths import shortest


def route_length(network, stops):
    """The length in km of a tour visiting ``stops`` in order."""
    return sum(shortest(network, a, b) for a, b in zip(stops, stops[1:], strict=False))
