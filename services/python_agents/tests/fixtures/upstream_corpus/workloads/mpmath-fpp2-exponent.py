"""OSS corpus benchmark: mpmath prints 9,860 numbers in shortest round-trip
form (``mp.shortest_str = True``) with ``str``, ``repr``, ``format`` and as
complex numbers, at five binary precisions (53 to 3,000 bits), as a
serialiser that must reproduce every value exactly does; magnitudes range
from 1e-320 to 1e+320 (wider at the higher precisions), and the printed
strings are parsed back and compared.

Copied into the cloned repository as ``benchmarks/bench_mpmath.py``.
Deterministic: a fixed seed, no clock, no network; prints a digest.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import mpmath
from mpmath import mp, mpc, mpf

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "mpmath" / "__init__.py"
LEVELS = (
    (53, 6000, 320),
    (113, 2000, 600),
    (200, 1500, 1000),
    (1000, 300, 2000),
    (3000, 60, 3000),
)
"""(bits of working precision, number of values, largest decimal exponent)."""


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(mpmath.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(f"mpmath imported from {mpmath.__file__}, not {PACKAGE_INIT}")


def _value(rng: random.Random, k: int, span: int):
    kind = k % 5
    if kind == 0:
        return mpf(rng.random())  # a double's mantissa
    if kind == 1:
        return mpf(rng.randint(1, 10**9)) / rng.randint(1, 10**9)
    if kind == 2:
        return mpf(10) ** rng.randint(-span, span) * (1 + mpf(rng.random()))
    if kind == 3:
        return mp.sqrt(rng.randint(2, 10**12)) * (-1) ** k
    return mp.exp(mpf(rng.randint(-span, span)) / 3)


def main() -> None:
    _checked()
    rng = random.Random(19)
    digest = hashlib.sha256()
    mp.shortest_str = True
    printed = mismatches = 0
    for bits, count, span in LEVELS:
        mp.prec = bits
        for k in range(count):
            value = _value(rng, k, span)
            text = str(value)
            digest.update(text.encode())
            printed += 1
            if k % 2 == 0:
                digest.update(repr(value).encode())
                printed += 1
            if k % 3 == 0:
                digest.update(format(value, "").encode())
                printed += 1
            if k % 7 == 0:
                digest.update(str(mpc(value, -value / 3)).encode())
                printed += 1
            if bits <= 200 and mpf(text) != value:
                mismatches += 1
    mp.shortest_str = False
    mp.prec = 53
    print(
        f"mpmath printed={printed} mismatches={mismatches} sha256={digest.hexdigest()}"
    )


if __name__ == "__main__":
    main()
