"""Choosing the vehicle that serves a job."""

from fleetsim.feed import Job
from fleetsim.fleet import Vehicle
from fleetsim.geometry import travel_minutes

TIER_WEIGHT = {"standard": 1.0, "express": 1.6, "priority": 2.4}


def ready_at(vehicle: Vehicle, job: Job) -> float:
    """When ``vehicle`` could be at the job's pickup."""
    start = max(vehicle.busy_until, job.appears)
    return start + travel_minutes(vehicle.location, job.pickup)


def score(vehicle: Vehicle, job: Job) -> float:
    """Lower is better: arrival time, weighted by how urgent the tier is,
    plus a penalty for a low battery."""
    arrival = ready_at(vehicle, job) - job.appears
    battery = (1 - vehicle.state_of_charge) * 15
    return arrival * TIER_WEIGHT[job.tier] + battery


def choose(fleet: list[Vehicle], job: Job) -> Vehicle | None:
    """The best vehicle with room and charge for ``job``; ties by name."""
    best: Vehicle | None = None
    best_score = 0.0
    for vehicle in fleet:
        if vehicle.load + job.parcels > vehicle.capacity:
            continue
        if not vehicle.can_reach(job.pickup) or not vehicle.can_reach(job.dropoff):
            continue
        value = score(vehicle, job)
        if best is None or (value, vehicle.name) < (best_score, best.name):
            best, best_score = vehicle, value
    return best
