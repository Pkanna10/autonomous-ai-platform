"""OSS corpus v2 benchmark: packaging parses 8,000 version strings (epochs,
pre, post and dev releases, local labels), sorts them, filters them
through 150 specifier sets and parses 4,000 requirements with markers.

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
VERSIONS = 8000
SPECIFIERS = 150
REQUIREMENTS = 4000
ENVIRONMENT = {
    "python_version": "3.12",
    "python_full_version": "3.12.4",
    "sys_platform": "linux",
    "platform_system": "Linux",
    "platform_machine": "x86_64",
    "implementation_name": "cpython",
    "os_name": "posix",
    "extra": "",
}


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(packaging.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"packaging imported from {packaging.__file__}, not {PACKAGE_INIT}"
        )


def _version(rng: random.Random) -> str:
    text = ".".join(str(rng.randint(0, 30)) for _ in range(rng.randint(1, 4)))
    if rng.random() < 0.1:
        text = f"{rng.randint(1, 3)}!{text}"
    if rng.random() < 0.3:
        text += f"{rng.choice(('a', 'b', 'rc', 'alpha', 'pre'))}{rng.randint(0, 9)}"
    if rng.random() < 0.2:
        text += f".post{rng.randint(0, 5)}"
    if rng.random() < 0.2:
        text += f".dev{rng.randint(0, 5)}"
    if rng.random() < 0.1:
        text += f"+local.{rng.randint(0, 99)}"
    return text


def _specifier(rng: random.Random) -> str:
    parts = []
    for _ in range(rng.randint(1, 3)):
        op = rng.choice((">=", "<", "!=", "~=", "==", "<=", ">"))
        base = f"{rng.randint(0, 25)}.{rng.randint(0, 25)}"
        parts.append(
            f"{op}{base}{'.*' if op in ('==', '!=') and rng.random() < 0.3 else ''}"
        )
    return ",".join(parts)


def _requirement(rng: random.Random, n: int) -> str:
    extras = f"[{','.join(rng.sample(('fast', 'docs', 'test', 'cli'), 2))}]"
    marker = rng.choice(
        (
            'python_version >= "3.9"',
            'sys_platform == "win32" or platform_machine == "arm64"',
            'python_full_version < "3.13" and os_name == "posix"',
            'implementation_name == "cpython" and extra == "test"',
        )
    )
    return f"package-{n % 97}{extras} {_specifier(rng)} ; {marker}"


def main() -> None:
    _checked()
    from packaging.requirements import Requirement
    from packaging.specifiers import SpecifierSet
    from packaging.version import Version

    rng = random.Random(23)
    digest = hashlib.sha256()
    versions = [Version(_version(rng)) for _ in range(VERSIONS)]
    ordered = sorted(versions)
    digest.update("|".join(str(v) for v in ordered).encode())
    for _ in range(SPECIFIERS):
        spec = SpecifierSet(_specifier(rng), prereleases=rng.random() < 0.5)
        kept = list(spec.filter(versions))
        digest.update(f"{spec}:{len(kept)}:{kept[:3]}".encode())
    matched = 0
    for n in range(REQUIREMENTS):
        requirement = Requirement(_requirement(rng, n))
        assert requirement.marker is not None
        matched += requirement.marker.evaluate(ENVIRONMENT)
        digest.update(str(requirement).encode())
    print(
        f"packaging versions={VERSIONS} matched={matched} sha256={digest.hexdigest()}"
    )


if __name__ == "__main__":
    main()
