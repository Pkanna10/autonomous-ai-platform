"""OSS corpus benchmark: idna encodes and decodes 4,000 internationalised
domain names with UTS 46 mapping, across five scripts.

Copied into the cloned repository as ``benchmarks/bench_idna.py``.
Deterministic: a fixed seed, no clock, no network (no DNS: only the codec
runs); prints a digest.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import idna

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "idna" / "__init__.py"
NAMES = 4000
ALPHABETS = (
    "abcdefghijklmnopqrstuvwxyzàéïñöøüß",
    "αβγδεζηθικλμνπρστω",
    "абвгдежзиклмнопрсту",
    "".join(chr(cp) for cp in range(0x4E00, 0x4E40)),
    "".join(chr(cp) for cp in range(0x3042, 0x3093, 2)),
)


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(idna.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(f"idna imported from {idna.__file__}, not {PACKAGE_INIT}")


def _label(rng: random.Random) -> str:
    alphabet = rng.choice(ALPHABETS)
    return "".join(rng.choice(alphabet) for _ in range(rng.randint(3, 12)))


def main() -> None:
    _checked()
    rng = random.Random(3)
    digest = hashlib.sha256()
    failures = 0
    for index in range(NAMES):
        labels = [_label(rng) for _ in range(rng.randint(1, 3))]
        name = ".".join(labels) + rng.choice((".com", ".org", ".example"))
        if index % 4 == 0:
            name = name.upper()  # UTS 46 maps case
        try:
            encoded = idna.encode(name, uts46=True)
            decoded = idna.decode(encoded)
        except idna.IDNAError as error:
            failures += 1
            digest.update(type(error).__name__.encode())
            continue
        digest.update(encoded + b"|" + decoded.encode())
    print(f"idna names={NAMES} failures={failures} sha256={digest.hexdigest()}")


if __name__ == "__main__":
    main()
