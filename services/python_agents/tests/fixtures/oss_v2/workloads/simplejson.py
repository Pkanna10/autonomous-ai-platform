"""OSS corpus v2 benchmark: simplejson (its pure-Python encoder and
scanner: the C speedups are not built in a checkout) encodes and decodes
a generated 2,000-record document (nested objects, arrays, escaped and
non-ASCII strings, floats, integers, booleans and nulls), sorted and
indented as well as compact, and as Decimal.

Copied into the cloned repository as ``benchmarks/bench_simplejson.py``.
Deterministic: a fixed seed, no clock, no network; prints a digest.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import simplejson

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "simplejson" / "__init__.py"
RECORDS = 2000


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(simplejson.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"simplejson imported from {simplejson.__file__}, not {PACKAGE_INIT}"
        )


def _record(rng: random.Random, n: int) -> dict[str, object]:
    return {
        "id": n,
        "name": f'user "{n}"\té中\\path',
        "score": rng.random() * 1000,
        "active": rng.random() < 0.5,
        "parent": None if n % 5 else n // 5,
        "tags": [f"tag-{rng.randint(0, 50)}" for _ in range(rng.randint(1, 5))],
        "address": {
            "city": rng.choice(("Oslo", "Lima", "Kyiv", "Pune")),
            "zip": f"{rng.randint(0, 99999):05d}",
            "geo": [rng.uniform(-90, 90), rng.uniform(-180, 180)],
        },
        "history": [{"day": d, "count": rng.randint(0, 9)} for d in range(4)],
    }


def main() -> None:
    _checked()
    rng = random.Random(59)
    document = {"records": [_record(rng, n) for n in range(RECORDS)]}
    digest = hashlib.sha256()
    compact = simplejson.dumps(document, separators=(",", ":"))
    pretty = simplejson.dumps(document, sort_keys=True, indent=2)
    ascii_only = simplejson.dumps(document, ensure_ascii=True)
    for text in (compact, pretty, ascii_only):
        digest.update(text.encode())
        if simplejson.loads(text) != document:
            raise SystemExit("the document did not round-trip")
    exact = simplejson.loads(compact, use_decimal=True)
    digest.update(simplejson.dumps(exact, use_decimal=True).encode())
    print(
        f"simplejson records={RECORDS} bytes={len(compact)} sha256={digest.hexdigest()}"
    )


if __name__ == "__main__":
    main()
