"""Sanity checks on a simulated day before its report is published."""

from fleetsim.feed import Job
from fleetsim.fleet import Vehicle
from fleetsim.simulation import Day


def check_outcomes(day: Day, jobs: list[Job]) -> list[str]:
    """What is inconsistent about the recorded outcomes."""
    problems: list[str] = []
    numbers = [outcome.job.number for outcome in day.outcomes]
    if len(numbers) != len(set(numbers)):
        problems.append("a job was delivered twice")
    known = {job.number for job in jobs}
    if not set(numbers) <= known:
        problems.append("a delivered job was never offered")
    for outcome in day.outcomes:
        if outcome.picked_up < outcome.job.appears:
            problems.append(f"job {outcome.job.number} picked up before it appeared")
        if outcome.delivered < outcome.picked_up:
            problems.append(f"job {outcome.job.number} delivered before pickup")
    return problems


def check_fleet(fleet: list[Vehicle]) -> list[str]:
    problems: list[str] = []
    names = [vehicle.name for vehicle in fleet]
    if len(names) != len(set(names)):
        problems.append("two vehicles share a name")
    for vehicle in fleet:
        if vehicle.load < 0 or vehicle.load > vehicle.capacity:
            problems.append(f"{vehicle.name} carries {vehicle.load} parcels")
        if not 0 <= vehicle.charge_kwh <= vehicle.battery_kwh + 1e-9:
            problems.append(f"{vehicle.name} battery out of range")
    return problems
