"""Orders: when each one arrived relative to the others."""

from shipmerge.data import Shipment


def order_numbers(lines: list[Shipment]) -> list[int]:
    """The distinct order numbers in ascending order."""
    return sorted({line.order_id for line in lines})


def arrival_ranks(lines: list[Shipment]) -> list[int]:
    """For each line, the rank of its order among all orders (0 = first)."""
    numbers = order_numbers(lines)
    return [numbers.index(line.order_id) for line in lines]


def rank_digest(ranks: list[int]) -> int:
    """A position-weighted checksum of ``ranks``."""
    total = 0
    for position, rank in enumerate(ranks):
        total = (total * 31 + rank * (position % 7 + 1)) % 1_000_000_007
    return total
