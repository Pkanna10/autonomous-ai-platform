"""Benchmark workload for sqlparse: ``python benchmarks/bench_p2.py bench.py``.

Runs the repository's own ``bench.py`` unchanged (its warm-up and rounds;
the timing it prints changes from run to run, so it is discarded), then one
more pass over the same inputs, and prints one deterministic line: the
sha256 of ``bench.py`` and its ``bench_data``, and of the library's outputs
(the dump and queries it processes, the parsed statements' types and grouped token trees).
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import runpy
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BENCH = "bench.py"
LIBRARY = "sqlparse"
INIT = ROOT / "sqlparse" / "__init__.py"


def _inputs() -> str:
    digest = hashlib.sha256()
    for path in (ROOT / BENCH, *sorted((ROOT / "bench_data").iterdir())):
        digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def _tree(token: Any) -> str:
    """A token as its class, type and value; a group as its class and children."""
    if token.is_group:
        inner = ",".join(_tree(t) for t in token.tokens)
        return f"{type(token).__name__}({inner})"
    return f"{type(token).__name__}:{token.ttype}:{token.value!r}"


def main() -> None:
    if sys.argv[1:] != [BENCH]:
        raise SystemExit(f"usage: {sys.argv[0]} {BENCH}")
    inputs = _inputs()
    bench = runpy.run_path(str(ROOT / BENCH))
    library = sys.modules[LIBRARY]
    if Path(str(library.__file__)).resolve() != INIT:
        raise SystemExit(f"{LIBRARY} imported from {library.__file__}, not {INIT}")
    with contextlib.redirect_stdout(io.StringIO()):
        bench["main"]()
    dump, queries = bench["load"]()
    out = hashlib.sha256()
    for text in library.split(dump):
        out.update(text.encode() + b"\0")
        for stmt in library.parse(text):
            out.update(f"{stmt.get_type()}\0{_tree(stmt)}\0".encode())
    for query in queries:
        formatted = library.format(query, reindent=True, keyword_case="upper")
        out.update(formatted.encode() + b"\0")
    print(f"p2 inputs={inputs} outputs={out.hexdigest()}")


if __name__ == "__main__":
    main()
