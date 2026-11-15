"""Benchmark workload for tomli: ``python benchmarks/bench_p1.py bench.py``.

Runs the repository's own ``bench.py`` unchanged (its warm-up and rounds;
the timing it prints changes from run to run, so it is discarded), then one
more pass over the same inputs, and prints one deterministic line: the
sha256 of ``bench.py`` and its ``bench_data``, and of the library's outputs
(the documents it parses).
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = "bench.py"
LIBRARY = "tomli"
INIT = ROOT / "src" / "tomli" / "__init__.py"


def _inputs() -> str:
    digest = hashlib.sha256()
    for path in (ROOT / BENCH, *sorted((ROOT / "bench_data").iterdir())):
        digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


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
    out = hashlib.sha256()
    for name, text in bench["load_documents"]().items():
        data = library.loads(text)
        out.update(name.encode() + b"\0")
        out.update(json.dumps(data, sort_keys=True, default=repr).encode() + b"\0")
    print(f"p1 inputs={inputs} outputs={out.hexdigest()}")


if __name__ == "__main__":
    main()
