"""OSS corpus benchmark: networkx runs a flow and connectivity analysis on one
seeded directed capacity network of 300 nodes and 2,400 edges: 20 maximum
flows that reuse one residual network, 10 minimum cuts, 6 maximum flows
with flow dictionaries, the node connectivity of the whole network, and 120
local node-connectivity queries that share one auxiliary digraph and
residual network, all with the Edmonds-Karp algorithm, the way the flow and
connectivity documentation shows.

Copied into the cloned repository as ``benchmarks/bench_networkx.py``.
Deterministic: a fixed seed, no clock, no network, no numpy; prints a
digest.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import networkx as nx
from networkx.algorithms.connectivity import (
    build_auxiliary_node_connectivity,
    local_node_connectivity,
)
from networkx.algorithms.flow import build_residual_network, edmonds_karp

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "networkx" / "__init__.py"
NODES = 300
EDGES = 2400
FLOWS = 20
CUTS = 10
FULL_FLOWS = 6
LOCAL = 120


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(nx.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(f"networkx imported from {nx.__file__}, not {PACKAGE_INIT}")


def _network(rng: random.Random) -> nx.DiGraph:
    graph = nx.gnm_random_graph(NODES, EDGES, seed=rng.randrange(10**9), directed=True)
    for _, _, data in graph.edges(data=True):
        data["capacity"] = rng.randint(1, 50)
    return graph


def _pair(rng: random.Random) -> tuple[int, int]:
    while True:
        s, t = rng.randrange(NODES), rng.randrange(NODES)
        if s != t:
            return s, t


def main() -> None:
    _checked()
    rng = random.Random(47)
    graph = _network(rng)
    digest = hashlib.sha256()
    residual = build_residual_network(graph, "capacity")
    total = 0
    for _ in range(FLOWS):
        s, t = _pair(rng)
        result = edmonds_karp(graph, s, t, residual=residual)
        value = result.graph["flow_value"]
        total += value
        digest.update(f"flow {s}->{t} {value}\n".encode())
    for _ in range(CUTS):
        s, t = _pair(rng)
        value, (reachable, non_reachable) = nx.minimum_cut(
            graph, s, t, flow_func=edmonds_karp
        )
        digest.update(
            f"cut {s}->{t} {value} {len(reachable)} {sorted(non_reachable)[:20]}\n".encode()
        )
    for _ in range(FULL_FLOWS):
        s, t = _pair(rng)
        value, flow = nx.maximum_flow(graph, s, t, flow_func=edmonds_karp)
        used = sum(1 for u in flow for v in flow[u] if flow[u][v] > 0)
        digest.update(f"maxflow {s}->{t} {value} {used}\n".encode())
    kappa = nx.node_connectivity(graph, flow_func=edmonds_karp)
    digest.update(f"connectivity node={kappa}\n".encode())
    auxiliary = build_auxiliary_node_connectivity(graph)
    shared = build_residual_network(auxiliary, "capacity")
    local = 0
    for _ in range(LOCAL):
        s, t = _pair(rng)
        k = local_node_connectivity(
            graph, s, t, flow_func=edmonds_karp, auxiliary=auxiliary,
            residual=shared, cutoff=4,
        )  # fmt: skip
        local += k
        digest.update(f"local {s}->{t} {k}\n".encode())
    print(
        f"networkx nodes={NODES} edges={EDGES} queries={FLOWS + CUTS + FULL_FLOWS + LOCAL} "
        f"total={total} local={local} sha256={digest.hexdigest()}"
    )


if __name__ == "__main__":
    main()
