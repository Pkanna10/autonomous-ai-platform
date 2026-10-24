"""Points on the city grid, distances and travel times."""

from dataclasses import dataclass

BLOCK_METRES = 120
CITY_KMH = 28.0
RING_KMH = 55.0
RING_RADIUS = 30  # blocks from the centre where the ring road runs


@dataclass(frozen=True, order=True)
class Point:
    x: int
    y: int

    def offset(self, dx: int, dy: int) -> "Point":
        return Point(self.x + dx, self.y + dy)


CENTRE = Point(0, 0)


def blocks(a: Point, b: Point) -> int:
    """Grid (Manhattan) distance in blocks."""
    return abs(a.x - b.x) + abs(a.y - b.y)


def metres(a: Point, b: Point) -> int:
    return blocks(a, b) * BLOCK_METRES


def ring_distance(p: Point) -> int:
    """How far ``p`` lies from the ring road, in blocks."""
    return abs(blocks(p, CENTRE) - RING_RADIUS)


def travel_minutes(a: Point, b: Point) -> float:
    """Minutes from ``a`` to ``b``: through the streets, or via the ring road
    when that is quicker (on and off the ring through the streets)."""
    street = metres(a, b) / 1000 / CITY_KMH * 60
    access = (ring_distance(a) + ring_distance(b)) * BLOCK_METRES / 1000
    along = abs(blocks(a, CENTRE) - blocks(b, CENTRE)) * BLOCK_METRES / 1000
    ring = access / CITY_KMH * 60 + (along + RING_RADIUS * 0.5) / RING_KMH * 60
    return min(street, ring)


def zone_of(p: Point) -> str:
    """``core`` inside the ring, ``ring`` near it, ``outer`` beyond."""
    distance = blocks(p, CENTRE)
    if distance < RING_RADIUS - 4:
        return "core"
    if distance <= RING_RADIUS + 4:
        return "ring"
    return "outer"


def bounding_box(points: list[Point]) -> tuple[Point, Point]:
    """The smallest box holding every point (lower-left, upper-right)."""
    if not points:
        raise ValueError("no points")
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    return Point(min(xs), min(ys)), Point(max(xs), max(ys))
