"""OSS corpus benchmark: tomli parses a generated 400-table TOML document
(strings with escapes, multi-line strings, integers in four bases, floats,
booleans, dates and times, arrays, inline tables, arrays of tables) eight
times.

Copied into the cloned repository as ``benchmarks/bench_tomli.py``.
Deterministic: a fixed seed, no clock, no network; prints a digest.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

import tomli

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "src" / "tomli" / "__init__.py"
TABLES = 400
REPEAT = 8


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(tomli.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(f"tomli imported from {tomli.__file__}, not {PACKAGE_INIT}")


def _document(rng: random.Random) -> str:
    lines: list[str] = []
    for n in range(TABLES):
        lines.append(f"[server_{n}]")
        lines.append(f'name = "host-{n}\\t\\u00e9\\"quoted\\""')
        lines.append(f"port = {rng.randint(1024, 65535)}")
        lines.append(f"mask = 0x{rng.randrange(1 << 16):04x}")
        lines.append(f"mode = 0o{rng.randrange(512):o}")
        lines.append(f"flags = 0b{rng.randrange(256):b}")
        lines.append(f"load = {rng.random() * 100:.4f}")
        lines.append(f"big = {rng.randint(1, 10**6):_}")
        lines.append(f"enabled = {'true' if rng.random() < 0.5 else 'false'}")
        lines.append(
            f"since = 2026-{n % 12 + 1:02d}-{n % 28 + 1:02d}T10:{n % 60:02d}:00Z"
        )
        lines.append(f"window = {n % 24:02d}:30:00")
        values = ", ".join(str(rng.randint(0, 999)) for _ in range(12))
        lines.append(f"samples = [{values}]")
        lines.append(f'tags = ["alpha", "beta-{n}", \'literal\\{n}\']')
        lines.append(
            f'owner = {{ name = "team-{n % 7}", level = {n % 3}, active = true }}'
        )
        lines.append(f'notes = """\nline one {n}\nline two \\\n  continued\n"""')
        lines.append(f"[[server_{n}.disk]]")
        lines.append(f'path = "/data/{n}"')
        lines.append(f"size_gb = {rng.randint(10, 2000)}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    _checked()
    text = _document(random.Random(31))
    digest = hashlib.sha256()
    for _ in range(REPEAT):
        data = tomli.loads(text)
        digest.update(json.dumps(data, sort_keys=True, default=str).encode())
    print(f"tomli tables={TABLES} bytes={len(text)} sha256={digest.hexdigest()}")


if __name__ == "__main__":
    main()
