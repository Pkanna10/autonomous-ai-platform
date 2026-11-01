"""OSS corpus benchmark: networkx builds random and lattice reference graphs
(``random_reference``, ``lattice_reference``) for three seeded small-world
graphs of 80 to 120 nodes and degree 4 with the connectivity check on, and
computes the small-world coefficient ``sigma`` for one of them, as a
network-science analysis does. The lattice references and ``sigma`` need
numpy: without it they are skipped and the printed line says so (the same
either way on one machine).

Copied into the cloned repository as ``benchmarks/bench_networkx.py``.
Deterministic: fixed seeds, no clock, no network; prints a digest.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "networkx" / "__init__.py"
GRAPHS = ((80, 4, 0.1, 101), (100, 4, 0.05, 102), (120, 4, 0.2, 103))


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(nx.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(f"networkx imported from {nx.__file__}, not {PACKAGE_INIT}")


def _summary(graph: nx.Graph) -> str:
    degrees = sorted(d for _, d in graph.degree())
    edges = hashlib.sha256()
    for u, v in sorted(tuple(sorted(e)) for e in graph.edges()):
        edges.update(f"{u},{v};".encode())
    return (
        f"m={graph.number_of_edges()} connected={nx.is_connected(graph)} "
        f"deg={degrees[0]}-{degrees[-1]} edges={edges.hexdigest()[:16]}"
    )


def main() -> None:
    _checked()
    try:
        import numpy  # noqa: F401  (lattice_reference and sigma need it)
    except ImportError:
        lattice = False
    else:
        lattice = True
    digest = hashlib.sha256()
    swaps = 0
    for index, (n, k, p, seed) in enumerate(GRAPHS):
        graph = nx.connected_watts_strogatz_graph(n, k, p, seed=seed)
        digest.update(f"input {index} {_summary(graph)}\n".encode())
        niter = 2 if index == 0 else 1
        randomised = nx.random_reference(graph, niter=niter, seed=seed + 10)
        swaps += niter * graph.number_of_edges()
        digest.update(f"random {index} {_summary(randomised)}\n".encode())
        if lattice:
            latticed = nx.lattice_reference(graph, niter=1, seed=seed + 20)
            digest.update(f"lattice {index} {_summary(latticed)}\n".encode())
    if lattice:  # sigma needs numpy as well
        first = nx.connected_watts_strogatz_graph(*GRAPHS[0][:3], seed=GRAPHS[0][3])
        sigma = nx.sigma(first, niter=1, nrand=1, seed=7)
        digest.update(f"sigma {sigma:.12g}\n".encode())
    print(
        f"networkx graphs={len(GRAPHS)} lattice={'on' if lattice else 'skipped'} "
        f"swaps={swaps} sha256={digest.hexdigest()}"
    )


if __name__ == "__main__":
    main()
