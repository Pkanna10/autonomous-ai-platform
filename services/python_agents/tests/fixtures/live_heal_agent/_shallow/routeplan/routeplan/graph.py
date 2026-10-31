"""Road networks: towns joined by two-way roads of a given length."""


class RouteError(LookupError):
    """No road connects the towns."""


class Network:
    """Towns and the roads between them (every road can be driven both ways)."""

    def __init__(self):
        self.roads = {}  # town -> {neighbour: km}

    def add_road(self, a, b, km):
        """A two-way road of ``km`` kilometres between towns ``a`` and ``b``."""
        self.roads.setdefault(a, {})[b] = km
        self.roads.setdefault(b, {})[a] = km

    def neighbours(self, town):
        """Every town one road away from ``town``, with the road's length."""
        return self.roads.get(town, {})


def parse(text):
    """A network written one road per line, as "a-b:km"; blank lines are
    skipped."""
    network = Network()
    for line in text.splitlines():
        line = line.strip()
        if line:
            ends, km = line.split(":")
            a, b = ends.split("-")
            network.add_road(a.strip(), b.strip(), float(km))
    return network
