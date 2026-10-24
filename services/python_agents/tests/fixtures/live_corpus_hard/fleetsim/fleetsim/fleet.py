"""Vehicles and depots."""

from dataclasses import dataclass, field

from fleetsim.geometry import Point, metres

KWH_PER_KM = 0.21
CHARGE_KW = 22.0


@dataclass(frozen=True)
class Depot:
    name: str
    location: Point
    chargers: int


@dataclass
class Vehicle:
    name: str
    depot: Depot
    capacity: int
    battery_kwh: float
    charge_kwh: float = 0.0
    location: Point = field(default=Point(0, 0))
    load: int = 0
    busy_until: float = 0.0
    driven_m: int = 0
    used_kwh: float = 0.0
    jobs_done: int = 0
    busy_minutes: float = 0.0

    def __post_init__(self) -> None:
        self.charge_kwh = self.battery_kwh
        self.location = self.depot.location

    def energy_for(self, target: Point) -> float:
        return metres(self.location, target) / 1000 * KWH_PER_KM

    def can_reach(self, target: Point, reserve: float = 0.15) -> bool:
        """Enough charge to drive to ``target`` and then home with a reserve."""
        there = self.energy_for(target)
        home = metres(target, self.depot.location) / 1000 * KWH_PER_KM
        return self.charge_kwh - there - home >= reserve * self.battery_kwh

    def drive(self, target: Point) -> None:
        energy = self.energy_for(target)
        self.driven_m += metres(self.location, target)
        self.charge_kwh -= energy
        self.used_kwh += energy
        self.location = target

    def charge_minutes(self) -> float:
        """Minutes to charge back to full at the depot."""
        return (self.battery_kwh - self.charge_kwh) / CHARGE_KW * 60

    def recharge(self) -> None:
        self.charge_kwh = self.battery_kwh

    @property
    def state_of_charge(self) -> float:
        return self.charge_kwh / self.battery_kwh


def utilisation(vehicle: Vehicle, day_minutes: float) -> float:
    """The share of the day ``vehicle`` was busy."""
    if day_minutes <= 0:
        raise ValueError("the day must have a length")
    return min(1.0, vehicle.busy_minutes / day_minutes)
