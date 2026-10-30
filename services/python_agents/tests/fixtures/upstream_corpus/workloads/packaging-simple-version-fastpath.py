"""OSS corpus benchmark: packaging parses 100,000 version strings the way a
resolver scanning a package index does (releases, calendar versions, ``v``
prefixes, epochs, pre, post and dev segments, local labels, odd case,
surrounding spaces, and a few invalid strings), then sorts them, prints a
sample, reads base versions and pre-release flags, and filters a sample
through ten specifier sets.

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
VERSIONS = 100000
SPECIFIERS = 10
SAMPLE = 2000


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(packaging.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"packaging imported from {packaging.__file__}, not {PACKAGE_INIT}"
        )


def _version(rng: random.Random, n: int) -> str:
    parts = rng.choice((1, 2, 2, 3, 3, 3, 4))
    text = ".".join(str(rng.randint(0, 30)) for _ in range(parts))
    if n % 100 < 65:
        return (
            text
            if n % 7
            else f"20{rng.randint(10, 26)}.{rng.randint(1, 12)}.{rng.randint(0, 9)}"
        )
    if rng.random() < 0.15:
        text = f"v{text}"
    if rng.random() < 0.1:
        text = f"{rng.randint(1, 3)}!{text}"
    if rng.random() < 0.5:
        text += rng.choice(
            ("a", "b", "rc", "alpha", "beta", "pre", "c", ".RC", "-rc")
        ) + str(rng.randint(0, 9))
    if rng.random() < 0.3:
        text += rng.choice((".post", "-", ".rev", "post")) + str(rng.randint(0, 5))
    if rng.random() < 0.3:
        text += rng.choice((".dev", "dev", "-dev")) + str(rng.randint(0, 5))
    if rng.random() < 0.2:
        text += f"+local.{rng.randint(0, 99)}.abc"
    if rng.random() < 0.1:
        text = f" {text.upper()} "
    if n % 50 == 0:
        text = rng.choice(("1.0.0-x", "latest", "1..2", "1.0+", "v", "1.0.0.post-1a"))
    return text


def _specifier(rng: random.Random) -> str:
    parts = []
    for _ in range(rng.randint(1, 3)):
        op = rng.choice((">=", "<", "!=", "~=", "==", "<=", ">", "==="))
        base = f"{rng.randint(0, 25)}.{rng.randint(0, 25)}"
        if op == "===":
            op, base = "==", f"{base}.*"
        elif op in ("==", "!=") and rng.random() < 0.3:
            base += ".*"
        elif op == "~=":
            base += ".0"
        parts.append(f"{op}{base}")
    return ",".join(parts)


def main() -> None:
    _checked()
    from packaging.specifiers import SpecifierSet
    from packaging.version import InvalidVersion, Version, parse

    rng = random.Random(23)
    digest = hashlib.sha256()
    versions = []
    invalid = 0
    for n in range(VERSIONS):
        text = _version(rng, n)
        try:
            version = Version(text) if n % 3 else parse(text)
        except InvalidVersion:
            invalid += 1
            continue
        versions.append(version)
    ordered = sorted(versions)
    digest.update("|".join(str(v) for v in ordered[::9]).encode())
    digest.update("|".join(v.base_version for v in ordered[::97]).encode())
    prereleases = sum(1 for v in versions if v.is_prerelease)
    newest = max(versions)
    digest.update(f"{newest!r} {newest.release} {newest.local} {prereleases}".encode())
    sample = versions[:SAMPLE]
    for _ in range(SPECIFIERS):
        spec = SpecifierSet(_specifier(rng), prereleases=rng.random() < 0.5)
        kept = list(spec.filter(sample))
        digest.update(f"{spec}:{len(kept)}:{kept[:3]}".encode())
    print(
        f"packaging versions={len(versions)} invalid={invalid} "
        f"prereleases={prereleases} sha256={digest.hexdigest()}"
    )


if __name__ == "__main__":
    main()
