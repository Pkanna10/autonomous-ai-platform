"""The audit trail's check values."""

MODULUS = 2_147_483_629


def line_digest(line: str) -> int:
    """A rolling check value of one movement line."""
    total = 7
    for byte in line.encode("ascii"):
        total = (total * 131 + byte) % MODULUS
    return total
