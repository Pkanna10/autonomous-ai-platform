"""The hash chain over the entries."""

import hashlib
from collections.abc import Iterable

GENESIS = bytes(32)


def seal(previous: bytes, entry: bytes) -> bytes:
    """The seal of ``entry`` after the seal ``previous``."""
    return hashlib.blake2b(previous + entry, digest_size=32).digest()


def seals(entries: Iterable[bytes]) -> list[bytes]:
    """The seal after each entry, in order."""
    out: list[bytes] = []
    previous = GENESIS
    for entry in entries:
        previous = seal(previous, entry)
        out.append(previous)
    return out


def seal_after(entries: Iterable[bytes], count: int) -> bytes:
    """The seal after the first ``count`` entries (``GENESIS`` for none)."""
    previous = GENESIS
    for number, entry in enumerate(entries):
        if number == count:
            break
        previous = seal(previous, entry)
    return previous
