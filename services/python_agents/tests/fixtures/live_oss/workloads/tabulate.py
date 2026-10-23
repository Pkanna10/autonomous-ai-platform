"""OSS corpus benchmark: tabulate renders a 6,000-row mixed table in four formats.

Copied into the cloned repository as ``benchmarks/bench_tabulate.py`` and
committed there, so it is the user's benchmark (protected: no trial edits
it). Deterministic: a fixed seed, no clock, no network; prints a digest.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import tabulate

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "tabulate" / "__init__.py"
ROWS = 6000
FORMATS = ("grid", "pipe", "simple", "fancy_grid")


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(tabulate.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"tabulate imported from {tabulate.__file__}, not {PACKAGE_INIT}"
        )


def main() -> None:
    _checked()
    rng = random.Random(20261023)
    groups = ("alpha", "beta", "gamma", None, "delta-long-name")
    rows = [
        (
            i,
            f"item-{rng.randrange(10**6):06d}",
            rng.random() * 1000,
            rng.choice(groups),
            rng.randint(-(10**5), 10**5),
            str(rng.randint(1, 9999)),
        )
        for i in range(ROWS)
    ]
    headers = ("id", "name", "score", "group", "delta", "code")
    digest = hashlib.sha256()
    for fmt in FORMATS:
        text = tabulate.tabulate(rows, headers, tablefmt=fmt, floatfmt=".3f")
        digest.update(text.encode())
    print(f"tabulate rows={ROWS} formats={len(FORMATS)} sha256={digest.hexdigest()}")


if __name__ == "__main__":
    main()
