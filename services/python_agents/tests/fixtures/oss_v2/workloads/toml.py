"""OSS corpus v2 benchmark: toml parses a generated 300-table TOML document
(escaped and multi-line strings, integers, floats, booleans, dates,
arrays, inline tables, arrays of tables) 16 times and dumps it back.

Copied into the cloned repository as ``benchmarks/bench_toml.py``.
Deterministic: a fixed seed, no clock, no network; prints a digest.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

import toml

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "toml" / "__init__.py"
TABLES = 300
REPEAT = 16


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(toml.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(f"toml imported from {toml.__file__}, not {PACKAGE_INIT}")


def _document(rng: random.Random) -> str:
    lines: list[str] = []
    for n in range(TABLES):
        lines.append(f"[service_{n}]")
        lines.append(f'name = "svc-{n}\\t\\u00e9\\"quoted\\""')
        lines.append(f"port = {rng.randint(1024, 65535)}")
        lines.append(f"weight = {rng.random() * 100:.4f}")
        lines.append(f"retries = {rng.randint(-5, 5)}")
        lines.append(f"enabled = {'true' if rng.random() < 0.5 else 'false'}")
        lines.append(
            f"since = 2026-{n % 12 + 1:02d}-{n % 28 + 1:02d}T08:{n % 60:02d}:00Z"
        )
        values = ", ".join(str(rng.randint(0, 999)) for _ in range(10))
        lines.append(f"samples = [{values}]")
        lines.append(f'tags = ["alpha", "beta-{n}", \'literal\\{n}\']')
        lines.append(f'owner = {{ name = "team-{n % 7}", level = {n % 3} }}')
        lines.append(f'notes = """\nfirst line {n}\nsecond line\n"""')
        lines.append(f"[[service_{n}.disk]]")
        lines.append(f'path = "/data/{n}"')
        lines.append(f"size_gb = {rng.randint(10, 2000)}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    _checked()
    text = _document(random.Random(29))
    digest = hashlib.sha256()
    for _ in range(REPEAT):
        data = toml.loads(text)
        digest.update(json.dumps(data, sort_keys=True, default=str).encode())
    digest.update(toml.dumps(data).encode())
    print(f"toml tables={TABLES} bytes={len(text)} sha256={digest.hexdigest()}")


if __name__ == "__main__":
    main()
