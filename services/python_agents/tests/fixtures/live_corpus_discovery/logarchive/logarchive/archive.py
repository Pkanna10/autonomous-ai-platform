"""The archive format: one deflate stream with size checkpoints."""

import zlib

PIECE = 4096
CHECKPOINT_EVERY = 64


def pack(log: bytes) -> tuple[bytes, list[int]]:
    """The archive of ``log`` and the archive size after every checkpoint."""
    stream = zlib.compressobj(9)
    parts: list[bytes] = []
    written = 0
    checkpoints: list[int] = []
    for number, start in enumerate(range(0, len(log), PIECE), 1):
        part = stream.compress(log[start : start + PIECE])
        parts.append(part)
        written += len(part)
        if number % CHECKPOINT_EVERY == 0:
            checkpoints = checkpoints + [written]
    parts.append(stream.flush())
    return b"".join(parts), checkpoints
