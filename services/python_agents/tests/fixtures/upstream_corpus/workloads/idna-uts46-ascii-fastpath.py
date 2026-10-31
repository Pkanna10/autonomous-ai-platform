"""OSS corpus benchmark: idna encodes and decodes 12,000 host names of one to
four labels with UTS 46 mapping, the way an HTTP client normalises every
host it connects to (mixed case, digits, hyphens, several scripts), and
remaps a sample of the names directly.

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
NAMES = 12000
ASCII = "abcdefghijklmnopqrstuvwxyz0123456789"
ALPHABETS = (
    "abcdefghijklmnopqrstuvwxyzàéïñöøüß",
    "αβγδεζηθικλμνπρστω",
    "абвгдежзиклмнопрсту",
    "".join(chr(cp) for cp in range(0x4E00, 0x4E40)),
    "".join(chr(cp) for cp in range(0x3042, 0x3093, 2)),
)
TLDS = (".com", ".org", ".net", ".example", ".co.uk", ".io")


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(idna.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(f"idna imported from {idna.__file__}, not {PACKAGE_INIT}")


def _ascii_label(rng: random.Random) -> str:
    length = rng.randint(2, 14)
    chars = [rng.choice(ASCII) for _ in range(length)]
    if length > 4 and rng.random() < 0.3:
        chars[rng.randrange(1, length - 1)] = "-"
    return "".join(chars)


def _idn_label(rng: random.Random) -> str:
    alphabet = rng.choice(ALPHABETS)
    return "".join(rng.choice(alphabet) for _ in range(rng.randint(3, 12)))


def _name(rng: random.Random, index: int) -> str:
    label = _ascii_label if index % 10 < 7 else _idn_label
    labels = [label(rng) for _ in range(rng.randint(1, 4))]
    name = ".".join(labels) + rng.choice(TLDS)
    if index % 4 == 0:
        name = name.upper()  # UTS 46 maps case
    elif index % 4 == 1:
        name = name.title()
    return name


def main() -> None:
    _checked()
    rng = random.Random(3)
    digest = hashlib.sha256()
    failures = 0
    for index in range(NAMES):
        name = _name(rng, index)
        try:
            encoded = idna.encode(name, uts46=True)
            decoded = idna.decode(encoded, uts46=True)
        except idna.IDNAError as error:
            failures += 1
            digest.update(type(error).__name__.encode())
            continue
        digest.update(encoded + b"|" + decoded.encode())
        if index % 8 == 0:
            digest.update(idna.uts46_remap(name).encode())
    print(f"idna names={NAMES} failures={failures} sha256={digest.hexdigest()}")


if __name__ == "__main__":
    main()
