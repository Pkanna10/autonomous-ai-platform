"""OSS corpus benchmark: networkx builds eleven complete r-ary trees with
``full_rary_tree`` and ``balanced_tree`` (branching factors 1 to 50, 3,000
to 32,767 nodes, undirected and directed) and reads their shape back
(leaves, maximum degree, depth from the root), as a hierarchy or
benchmark-graph generator does.

Copied into the cloned repository as ``benchmarks/bench_networkx.py``.
Deterministic: no randomness, no clock, no network, no numpy; prints a
digest.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "networkx" / "__init__.py"
TREES = (
    (2, 30000, None),
    (3, 30000, None),
    (4, 25000, None),
    (8, 25000, None),
    (16, 20000, None),
    (50, 20000, None),
    (1, 3000, None),
    (2, 30000, nx.DiGraph),
    (6, 15000, nx.DiGraph),
)
BALANCED = ((2, 14), (3, 9))


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(nx.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(f"networkx imported from {nx.__file__}, not {PACKAGE_INIT}")


def _shape(graph: nx.Graph) -> str:
    degrees = [d for _, d in graph.degree()]
    depth = max(nx.single_source_shortest_path_length(graph, 0).values())
    leaves = sum(1 for d in degrees if d == 1)
    edge_hash = hashlib.sha256()
    for u, v in graph.edges():
        edge_hash.update(f"{u},{v};".encode())
    return (
        f"n={graph.number_of_nodes()} m={graph.number_of_edges()} leaves={leaves} "
        f"maxdeg={max(degrees)} depth={depth} edges={edge_hash.hexdigest()[:16]}"
    )


def main() -> None:
    _checked()
    digest = hashlib.sha256()
    nodes = 0
    for r, n, create_using in TREES:
        graph = nx.full_rary_tree(r, n, create_using=create_using)
        nodes += graph.number_of_nodes()
        digest.update(f"rary r={r} {_shape(graph)}\n".encode())
    for r, h in BALANCED:
        graph = nx.balanced_tree(r, h)
        nodes += graph.number_of_nodes()
        digest.update(f"balanced r={r} h={h} {_shape(graph)}\n".encode())
    print(
        f"networkx trees={len(TREES) + len(BALANCED)} nodes={nodes} sha256={digest.hexdigest()}"
    )


if __name__ == "__main__":
    main()
