"""OSS corpus benchmark: mpmath dumps a table of multiprecision constants and
computed values as hexadecimal, binary and octal digit strings at working
precisions from 30 to 20,000 decimal digits, the way a generator of
bit-exact test vectors for an arbitrary-precision library does; one value in
four is also printed in decimal and parsed back.

Copied into the cloned repository as ``benchmarks/bench_mpmath.py``.
Deterministic: a fixed seed, no clock, no network; prints a digest.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import mpmath
from mpmath import mp, mpf, nstr

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "mpmath" / "__init__.py"
LEVELS = ((30, 2000), (100, 1000), (1000, 300), (5000, 40), (20000, 6))
"""(decimal digits of working precision, number of values dumped)."""


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(mpmath.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(f"mpmath imported from {mpmath.__file__}, not {PACKAGE_INIT}")


def _values(rng: random.Random, count: int, dps: int) -> list:
    constants = [mp.pi, mp.e, mp.sqrt(2), mp.log(10)]
    if dps <= 1000:  # Euler's and Catalan's constants are slow to compute past that
        constants += [mp.euler, mp.catalan]
    values = []
    for k in range(count):
        kind = k % 6
        if kind == 0:
            values.append(constants[k // 6 % len(constants)])
        elif kind == 1:
            values.append(mpf(rng.randint(1, 999)) / rng.randint(1, 999))
        elif kind == 2:
            values.append(mp.exp(mpf(rng.randint(-40, 40)) / 7))
        elif kind == 3:
            values.append(mp.pi * rng.randint(1, 10**6))
        elif kind == 4:
            values.append(mpf(2) ** rng.randint(-200, 200) * mp.e)
        else:
            values.append(-mp.sqrt(rng.randint(2, 10**6)))
    return values


def main() -> None:
    _checked()
    rng = random.Random(17)
    digest = hashlib.sha256()
    conversions = 0
    for dps, count in LEVELS:
        mp.dps = dps
        hex_digits = dps * 5 // 6 + 1  # about the same information as dps decimals
        for index, value in enumerate(_values(rng, count, dps)):
            digest.update(nstr(value, hex_digits, base=16).encode())
            digest.update(nstr(value, hex_digits * 4 // 3 + 1, base=8).encode())
            digest.update(nstr(value, hex_digits * 4, base=2).encode())
            conversions += 3
            if index % 4 == 0:
                decimal = str(value)
                digest.update(decimal.encode())
                back = mpf(decimal)
                digest.update(nstr(back - value, 5).encode())
                conversions += 2
    mp.dps = 15
    print(f"mpmath conversions={conversions} sha256={digest.hexdigest()}")


if __name__ == "__main__":
    main()
