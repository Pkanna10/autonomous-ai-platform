"""OSS corpus v2 benchmark: networkx runs pure-Python graph algorithms on a
seeded 600-node weighted graph: betweenness centrality, Dijkstra from 40
sources, a minimum spanning tree, clustering, components and core numbers.
The graph is sized so the algorithms, not ``import networkx`` (about 0.5 s
with no bytecode cache, which no trial can change), are most of a run.

Copied into the cloned repository as ``benchmarks/bench_networkx.py``.
Deterministic: a fixed seed, no clock, no network, no numpy; prints a
digest (floats rounded to 12 significant digits).
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import networkx

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "networkx" / "__init__.py"
NODES = 600
EDGES = 3600
SOURCES = 40


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(networkx.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"networkx imported from {networkx.__file__}, not {PACKAGE_INIT}"
        )


def _graph(rng: random.Random) -> networkx.Graph:
    graph = networkx.Graph()
    graph.add_nodes_from(range(NODES))
    edges = 0
    while edges < EDGES:
        a, b = rng.randrange(NODES), rng.randrange(NODES)
        if a != b and not graph.has_edge(a, b):
            graph.add_edge(a, b, weight=rng.randint(1, 20))
            edges += 1
    return graph


def _fmt(values: dict[int, float]) -> str:
    return ",".join(f"{k}:{v:.12g}" for k, v in sorted(values.items()))


def main() -> None:
    _checked()
    graph = _graph(random.Random(43))
    digest = hashlib.sha256()
    digest.update(
        _fmt(networkx.betweenness_centrality(graph, weight="weight")).encode()
    )
    for source in range(SOURCES):
        lengths = networkx.single_source_dijkstra_path_length(graph, source)
        digest.update(_fmt(lengths).encode())
    tree = networkx.minimum_spanning_tree(graph, algorithm="kruskal")
    weight = tree.size(weight="weight")
    digest.update(f"mst:{weight}:{sorted(tree.edges())[:40]}".encode())
    digest.update(_fmt(networkx.clustering(graph)).encode())
    digest.update(repr(sorted(networkx.core_number(graph).items())).encode())
    components = [sorted(c) for c in networkx.connected_components(graph)]
    digest.update(repr(sorted(components)).encode())
    print(
        f"networkx nodes={NODES} edges={EDGES} mst={weight} "
        f"components={len(components)} sha256={digest.hexdigest()}"
    )


if __name__ == "__main__":
    main()
