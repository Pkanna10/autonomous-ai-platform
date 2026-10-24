"""The event loop of one simulated day."""

from dataclasses import dataclass, field

from fleetsim.agenda import Agenda
from fleetsim.dispatch import choose
from fleetsim.feed import Job
from fleetsim.fleet import Vehicle
from fleetsim.geometry import travel_minutes

LOAD_MINUTES = 3.0
UNLOAD_MINUTES = 2.0
RETRY_MINUTES = 10.0


@dataclass
class Outcome:
    job: Job
    vehicle: str
    picked_up: float
    delivered: float

    @property
    def wait(self) -> float:
        """Minutes from the job appearing to its delivery."""
        return self.delivered - self.job.appears

    @property
    def on_time(self) -> bool:
        return self.delivered <= self.job.promise


@dataclass
class Day:
    outcomes: list[Outcome] = field(default_factory=list)
    retries: int = 0
    recharges: int = 0
    events: int = 0


def run_day(fleet: list[Vehicle], jobs: list[Job], day_minutes: float) -> Day:
    """Simulate the day: each job is dispatched when it appears, retried
    later when no vehicle can take it, until the day ends."""
    agenda = Agenda()
    for job in jobs:
        agenda.add(job.appears, "job", job.number)
    by_number = {job.number: job for job in jobs}
    day = Day()
    while len(agenda):
        event = agenda.next()
        day.events += 1
        if event.kind == "job":
            job = by_number[event.subject]
            vehicle = choose(fleet, job)
            if vehicle is None:
                if event.at + RETRY_MINUTES <= day_minutes:
                    day.retries += 1
                    agenda.add(event.at + RETRY_MINUTES, "job", job.number)
                continue
            day.outcomes.append(serve(vehicle, job, event.at))
            index = fleet.index(vehicle)
            if vehicle.state_of_charge < 0.35:
                agenda.add(vehicle.busy_until, "recharge", index)
        elif event.kind == "recharge":
            vehicle = fleet[event.subject]
            home = travel_minutes(vehicle.location, vehicle.depot.location)
            vehicle.drive(vehicle.depot.location)
            minutes = home + vehicle.charge_minutes()
            vehicle.recharge()
            vehicle.busy_until = max(vehicle.busy_until, event.at) + minutes
            vehicle.busy_minutes += minutes
            vehicle.load = 0
            day.recharges += 1
    return day


def serve(vehicle: Vehicle, job: Job, now: float) -> Outcome:
    """Drive to the pickup, load, drive to the drop-off and unload."""
    start = max(vehicle.busy_until, now)
    to_pickup = travel_minutes(vehicle.location, job.pickup)
    vehicle.drive(job.pickup)
    picked = start + to_pickup + LOAD_MINUTES
    vehicle.load += job.parcels
    to_drop = travel_minutes(job.pickup, job.dropoff)
    vehicle.drive(job.dropoff)
    delivered = picked + to_drop + UNLOAD_MINUTES
    vehicle.load -= job.parcels
    vehicle.busy_minutes += delivered - start
    vehicle.busy_until = delivered
    vehicle.jobs_done += 1
    return Outcome(job, vehicle.name, round(picked, 3), round(delivered, 3))
