"""OSS corpus benchmark: packaging parses 15,000 requirement strings with
environment markers and then does what a resolver does with them: prints
each requirement, deduplicates the markers through a set and a dict keyed
by their text, sorts them by text, evaluates them against one environment,
compares neighbours, parses 3,000 markers directly and pickles 2,000.

Copied into the cloned repository as ``benchmarks/bench_packaging.py``.
Deterministic: a fixed seed, no clock, no network; prints a digest.
"""

from __future__ import annotations

import hashlib
import pickle
import random
from pathlib import Path

import packaging

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "src" / "packaging" / "__init__.py"
REQUIREMENTS = 15000
MARKERS = 3000
PICKLED = 2000
ENVIRONMENT = {
    "python_version": "3.12",
    "python_full_version": "3.12.4",
    "sys_platform": "linux",
    "platform_system": "Linux",
    "platform_machine": "x86_64",
    "platform_python_implementation": "CPython",
    "implementation_name": "cpython",
    "implementation_version": "3.12.4",
    "os_name": "posix",
    "platform_release": "6.8.0",
    "platform_version": "#1 SMP",
    "extra": "",
}
CLAUSES = (
    'python_version >= "3.{}"',
    'python_version < "3.{}"',
    'python_full_version >= "3.{}.2"',
    'sys_platform == "win32"',
    'sys_platform != "darwin"',
    'platform_machine in "x86_64 AMD64 arm64"',
    'platform_machine not in "ppc64le s390x"',
    'os_name == "posix"',
    'implementation_name == "cpython"',
    'platform_python_implementation != "PyPy"',
    'extra == "test"',
    'extra == "docs"',
    'platform_system == "Linux"',
    '"3.{}" <= python_version',
)


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(packaging.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"packaging imported from {packaging.__file__}, not {PACKAGE_INIT}"
        )


def _clause(rng: random.Random) -> str:
    return rng.choice(CLAUSES).format(rng.randint(6, 14))


def _marker(rng: random.Random) -> str:
    count = rng.randint(1, 4)
    clauses = [_clause(rng) for _ in range(count)]
    if count >= 3 and rng.random() < 0.5:
        inner = f"({clauses[1]} or {clauses[2]})"
        clauses = [clauses[0], inner, *clauses[3:]]
    joined = clauses[0]
    for clause in clauses[1:]:
        joined += rng.choice((" and ", " or ")) + clause
    return joined


def _requirement(rng: random.Random, n: int) -> str:
    name = f"package-{n % 400}"
    extras = f"[{','.join(rng.sample(('fast', 'docs', 'test', 'cli', 'all'), rng.randint(0, 2)))}]"
    if extras == "[]":
        extras = ""
    spec = rng.choice(("", ">=1.0", ">=1.2,<2", "==3.1.*", "~=2.4", "!=1.5"))
    if n % 9 == 0:
        return (
            f"{name}{extras} @ https://example.org/{name}-1.0.tar.gz ; {_marker(rng)}"
        )
    return f"{name}{extras}{spec}; {_marker(rng)}"


def main() -> None:
    _checked()
    from packaging.markers import Marker
    from packaging.requirements import Requirement

    rng = random.Random(53)
    digest = hashlib.sha256()
    requirements = [Requirement(_requirement(rng, n)) for n in range(REQUIREMENTS)]
    digest.update("\n".join(str(r) for r in requirements[::7]).encode())
    markers = [r.marker for r in requirements if r.marker is not None]
    distinct = set(markers)
    by_text: dict[str, int] = {}
    for marker in markers:
        by_text[str(marker)] = by_text.get(str(marker), 0) + 1
    ordered = sorted(distinct, key=str)
    digest.update("\n".join(str(m) for m in ordered[::5]).encode())
    matched = sum(1 for m in markers if m.evaluate(ENVIRONMENT))
    same = sum(1 for a, b in zip(markers, markers[1:], strict=False) if a == b)
    direct = [Marker(_marker(rng)) for _ in range(MARKERS)]
    digest.update("\n".join(repr(m) for m in direct[::11]).encode())
    restored = [pickle.loads(pickle.dumps(m)) for m in markers[:PICKLED]]
    assert all(a == b for a, b in zip(restored, markers, strict=False)), (
        "pickle round trip changed a marker"
    )
    print(
        f"packaging requirements={REQUIREMENTS} distinct={len(distinct)} "
        f"texts={len(by_text)} matched={matched} same={same} sha256={digest.hexdigest()}"
    )


if __name__ == "__main__":
    main()
