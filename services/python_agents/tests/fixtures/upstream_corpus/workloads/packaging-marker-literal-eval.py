"""OSS corpus benchmark: packaging parses 24,000 environment markers and
8,000 requirements with markers and evaluates every marker against one
environment, as a lock-file consumer deciding which dependencies apply to
the running interpreter does. Markers have one to four clauses with quoted
values of every shape (short versions, platform names, long
``platform_version`` strings with escapes, single and double quotes).

Copied into the cloned repository as ``benchmarks/bench_packaging.py``.
Deterministic: a fixed seed, no clock, no network; prints a digest.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import packaging

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "src" / "packaging" / "__init__.py"
MARKERS = 24000
REQUIREMENTS = 8000
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
    "platform_release": "6.8.0-45-generic",
    "platform_version": "#45~22.04.1-Ubuntu SMP PREEMPT_DYNAMIC Mon Sep  9 12:00:00 UTC 2",
    "extra": "",
}
VALUES = (
    ("python_version", "{q}3.{n}{q}"),
    ("python_full_version", "{q}3.{n}.{m}{q}"),
    ("sys_platform", "{q}{platform}{q}"),
    ("platform_machine", "{q}{machine}{q}"),
    ("platform_version", "{q}#1 SMP Debian 6.{n}.{m}-1 (2024-0{m}-0{n})\\n{q}"),
    ("platform_release", "{q}{n}.{m}.0-{n}{m}-generic{q}"),
    ("implementation_name", "{q}cpython{q}"),
    ("extra", "{q}extra-{n}{q}"),
    ("os_name", "{q}posix{q}"),
)
OPS = ("==", "!=", ">=", "<", "<=", ">", "~=", "===")


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(packaging.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"packaging imported from {packaging.__file__}, not {PACKAGE_INIT}"
        )


def _clause(rng: random.Random) -> str:
    variable, template = rng.choice(VALUES)
    value = template.format(
        q=rng.choice(("'", '"')),
        n=rng.randint(6, 14),
        m=rng.randint(0, 20),
        platform=rng.choice(("linux", "win32", "darwin", "cygwin", "linux2")),
        machine=rng.choice(("x86_64", "AMD64", "arm64", "aarch64", "ppc64le")),
    )
    if variable in ("platform_machine", "sys_platform") and rng.random() < 0.3:
        return f"{variable} {rng.choice(('in', 'not in'))} {value[0]}x86_64 arm64 {value[1:]}"
    if variable in ("python_version", "python_full_version"):
        op = rng.choice(OPS)  # version comparisons, including ~= and ===
    elif variable in ("platform_version", "platform_release"):
        op = rng.choice(("==", "!=", ">=", "<"))  # string comparisons
    else:
        op = rng.choice(("==", "!="))
    if rng.random() < 0.2:
        return f"{value} {op} {variable}"
    return f"{variable} {op} {value}"


def _marker(rng: random.Random) -> str:
    clauses = [_clause(rng) for _ in range(rng.randint(1, 4))]
    if len(clauses) >= 3 and rng.random() < 0.5:
        clauses[1] = f"({clauses[1]} or {clauses[2]})"
        del clauses[2]
    joined = clauses[0]
    for clause in clauses[1:]:
        joined += rng.choice((" and ", " or ")) + clause
    return joined


def main() -> None:
    _checked()
    from packaging.markers import InvalidMarker, Marker
    from packaging.requirements import Requirement

    rng = random.Random(59)
    digest = hashlib.sha256()
    matched = invalid = 0
    for n in range(MARKERS):
        text = _marker(rng)
        try:
            marker = Marker(text)
        except InvalidMarker as error:
            invalid += 1
            digest.update(str(error)[:40].encode())
            continue
        matched += marker.evaluate(ENVIRONMENT)
        if n % 10 == 0:
            digest.update(str(marker).encode())
    for n in range(REQUIREMENTS):
        requirement = Requirement(f"package-{n % 300}>=1.{n % 9} ; {_marker(rng)}")
        if n % 10 == 0:
            digest.update(str(requirement).encode())
    print(
        f"packaging markers={MARKERS} requirements={REQUIREMENTS} matched={matched} "
        f"invalid={invalid} sha256={digest.hexdigest()}"
    )


if __name__ == "__main__":
    main()
