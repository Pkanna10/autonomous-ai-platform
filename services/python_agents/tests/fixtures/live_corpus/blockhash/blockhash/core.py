"""Digesting blocks."""

import hashlib

BLOCK = bytes(range(256)) * 4096
"""One 1 MiB block of the image."""


def image_digest(blocks: int) -> str:
    """SHA-256 over ``blocks`` blocks, each followed by its 4-byte number."""
    digest = hashlib.sha256()
    for number in range(blocks):
        digest.update(BLOCK)
        digest.update(number.to_bytes(4, "big"))
    return digest.hexdigest()
