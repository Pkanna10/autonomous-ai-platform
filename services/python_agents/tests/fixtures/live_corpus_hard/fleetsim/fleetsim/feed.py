"""The deterministic city: depots, vehicles and the day's jobs."""

from dataclasses import dataclass

from fleetsim.fleet import Depot, Vehicle
from fleetsim.geometry import Point

TIERS = ("standard", "express", "priority")
PROMISE_MINUTES = {"standard": 240.0, "express": 120.0, "priority": 60.0}


@dataclass(frozen=True)
class Job:
    number: int
    appears: float  # minutes after the start of the day
    pickup: Point
    dropoff: Point
    parcels: int
    tier: str

    @property
    def promise(self) -> float:
        """The latest delivery time the customer was promised."""
        return self.appears + PROMISE_MINUTES[self.tier]


class Lcg:
    def __init__(self, seed: int) -> None:
        self.state = seed

    def next(self) -> int:
        self.state = (self.state * 1103515245 + 12345) % (1 << 31)
        return self.state >> 4

    def between(self, low: int, high: int) -> int:
        return low + self.next() % (high - low + 1)


def depots() -> list[Depot]:
    return [
        Depot("north", Point(0, 20), 6),
        Depot("east", Point(21, -3), 5),
        Depot("south", Point(-5, -19), 6),
        Depot("west", Point(-20, 6), 4),
        Depot("central", Point(2, 1), 8),
    ]


def vehicles(per_depot: int, seed: int = 9) -> list[Vehicle]:
    rng = Lcg(seed)
    fleet: list[Vehicle] = []
    for depot in depots():
        for index in range(per_depot):
            fleet.append(
                Vehicle(
                    name=f"{depot.name}-{index:02d}",
                    depot=depot,
                    capacity=rng.between(20, 60),
                    battery_kwh=float(rng.between(40, 75)),
                )
            )
    return fleet


def past_waits(count: int, seed: int = 57) -> list[float]:
    """``count`` waiting times (minutes) recorded on earlier days, the
    reference a day's service is measured against."""
    rng = Lcg(seed)
    return [
        rng.between(150, 4000) / 10 + rng.between(0, 99) / 1000 for _ in range(count)
    ]


def jobs(count: int, day_minutes: float, seed: int = 31) -> list[Job]:
    """``count`` jobs spread over the day, in order of appearance."""
    rng = Lcg(seed)
    out: list[Job] = []
    for number in range(count):
        appears = number * day_minutes / count + rng.between(0, 9) / 10
        tier = TIERS[0 if rng.next() % 10 < 6 else (1 if rng.next() % 3 else 2)]
        out.append(
            Job(
                number=number,
                appears=round(appears, 1),
                pickup=Point(rng.between(-24, 24), rng.between(-24, 24)),
                dropoff=Point(rng.between(-26, 26), rng.between(-26, 26)),
                parcels=rng.between(1, 12),
                tier=tier,
            )
        )
    return out
