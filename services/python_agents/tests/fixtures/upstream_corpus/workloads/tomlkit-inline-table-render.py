"""OSS corpus benchmark: tomlkit parses a generated pyproject-style document
of about 150 KB whose 900 dependency entries and 80 build-matrix entries
are inline tables (3 to 6 keys, and 30 to 60 keys with nested inline tables
and arrays), dumps it, edits it the way a dependency updater does (bump
versions, add keys, remove keys, add 300 new inline tables built with the
API) and dumps it twice more.

Copied into the cloned repository as ``benchmarks/bench_tomlkit.py``.
Deterministic: a fixed seed, no clock, no network; prints a digest.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import tomlkit

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "tomlkit" / "__init__.py"
SMALL = 900
BIG = 80
NEW = 300
WORDS = ("engine", "trial", "judge", "verdict", "noise", "branch", "profile", "cache")


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(tomlkit.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"tomlkit imported from {tomlkit.__file__}, not {PACKAGE_INIT}"
        )


def _dependency(rng: random.Random, n: int) -> str:
    parts = [f'version = "^{rng.randint(0, 9)}.{rng.randint(0, 20)}"']
    if rng.random() < 0.4:
        parts.append(f"optional = {'true' if n % 2 else 'false'}")
    if rng.random() < 0.4:
        parts.append(f'extras = ["{rng.choice(WORDS)}", "{rng.choice(WORDS)}"]')
    if rng.random() < 0.3:
        parts.append(f'markers = "python_version >= \\"3.{rng.randint(8, 13)}\\""')
    if rng.random() < 0.2:
        parts.append(f'source = {{ name = "{rng.choice(WORDS)}", priority = {n % 3} }}')
    if rng.random() < 0.3:
        parts.append(f'python = ">={n % 4 + 8}"  ')
    return f"dep-{n} = {{ {', '.join(parts)} }}  # dependency {n}\n"


def _matrix_value(rng: random.Random) -> str:
    kind = rng.randrange(6)
    if kind == 0:
        return str(rng.randint(0, 999))
    if kind == 1:
        return "true"
    if kind == 2:
        return '"' + rng.choice(WORDS) + '"'
    if kind == 3:
        return "[1, 2, 3]"
    if kind == 4:
        return "{ a = 1, b = { c = 2 } }"
    return "3.5"


def _matrix(rng: random.Random, n: int) -> str:
    keys = [f"k{k} = {_matrix_value(rng)}" for k in range(rng.randint(30, 60))]
    return f"matrix_{n} = {{ {', '.join(keys)} }}\n"


def _document(rng: random.Random) -> str:
    lines = [
        '[project]\nname = "bench"\nversion = "0.1.0"\n\n[tool.poetry.dependencies]\npython = "^3.11"\n'
    ]
    lines += [_dependency(rng, n) for n in range(SMALL)]
    lines.append("\n[tool.bench.matrix]\n")
    lines += [_matrix(rng, n) for n in range(BIG)]
    return "".join(lines)


def main() -> None:
    _checked()
    rng = random.Random(101)
    text = _document(rng)
    digest = hashlib.sha256()
    doc = tomlkit.parse(text)
    first = tomlkit.dumps(doc)
    digest.update(first.encode())

    dependencies = doc["tool"]["poetry"]["dependencies"]
    for n in range(0, SMALL, 3):
        entry = dependencies[f"dep-{n}"]
        entry["version"] = f"^{rng.randint(10, 19)}.0"
        if n % 2 == 0:
            entry["source"] = "pypi"
        elif "extras" in entry:
            del entry["extras"]
    matrix = doc["tool"]["bench"]["matrix"]
    for n in range(BIG):
        table = matrix[f"matrix_{n}"]
        for key in list(table.keys())[::7]:
            del table[key]
        table["added"] = n
    second = tomlkit.dumps(doc)
    digest.update(second.encode())

    added = tomlkit.table()
    for n in range(NEW):
        inline = tomlkit.inline_table()
        inline.update({"version": f"=={n}.0", "optional": n % 2 == 0})
        inline.append("extras", [rng.choice(WORDS), rng.choice(WORDS)])
        if n % 5 == 0:
            nested = tomlkit.inline_table()
            nested.update({"name": rng.choice(WORDS), "priority": n % 3})
            inline["source"] = nested
        added[f"new-{n}"] = inline
    doc["tool"]["poetry"]["group"] = added
    third = tomlkit.dumps(doc)
    digest.update(third.encode())
    print(
        f"tomlkit bytes_in={len(text)} dumps={len(first)}/{len(second)}/{len(third)} "
        f"sha256={digest.hexdigest()}"
    )


if __name__ == "__main__":
    main()
