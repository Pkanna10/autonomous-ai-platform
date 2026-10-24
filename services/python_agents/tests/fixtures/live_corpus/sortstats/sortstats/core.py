"""Sampling and order statistics."""

import random
import zlib
from array import array


def sample(count: int, seed: int = 7) -> list[int]:
    """``count`` unsigned 32-bit readings from a seeded generator."""
    readings = array("I")
    readings.frombytes(random.Random(seed).randbytes(4 * count))
    return readings.tolist()


def order_stats(ordered: list[int]) -> dict[str, int]:
    """Minimum, quartiles and maximum of the sorted ``ordered`` (nearest rank)."""
    last = len(ordered) - 1
    return {
        "min": ordered[0],
        "q1": ordered[last // 4],
        "median": ordered[last // 2],
        "q3": ordered[3 * last // 4],
        "max": ordered[last],
    }


def checksum(ordered: list[int]) -> int:
    """CRC-32 of ``ordered`` as native 32-bit words."""
    return zlib.crc32(array("I", ordered).tobytes())
