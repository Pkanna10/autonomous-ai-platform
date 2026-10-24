"""The end-of-day report."""

from fleetsim.fleet import Vehicle, utilisation
from fleetsim.metrics import histogram, mean, percentile, spread
from fleetsim.service import on_time_by_tier, per_job, worst_standing
from fleetsim.simulation import Day


def waits_section(day: Day) -> list[str]:
    waits = [outcome.wait for outcome in day.outcomes]
    lines = [
        f"delivered {len(waits)}, retries {day.retries}, recharges {day.recharges}",
        f"wait mean {mean(waits):.2f} min, spread {spread(waits):.2f}",
    ]
    for q in (50, 90, 95, 99):
        lines.append(f"wait p{q} {percentile(waits, q):.2f} min")
    lines.append("histogram " + " ".join(map(str, histogram(waits, 30.0, 10))))
    return lines


def tiers_section(day: Day, past: list[float]) -> list[str]:
    lines: list[str] = []
    services = per_job(day.outcomes, past)
    for tier, (on_time, delivered) in on_time_by_tier(day.outcomes).items():
        share = 100 * on_time / delivered
        worst = worst_standing(services, tier, 3)
        lines.append(
            f"{tier}: {on_time}/{delivered} on time ({share:.1f} %), worst {worst}"
        )
    standing = sum(s.standing for s in services) / len(services)
    lines.append(f"mean standing {standing:.4f}")
    return lines


def fleet_section(fleet: list[Vehicle], day_minutes: float) -> list[str]:
    lines: list[str] = []
    by_depot: dict[str, list[Vehicle]] = {}
    for vehicle in fleet:
        by_depot.setdefault(vehicle.depot.name, []).append(vehicle)
    for depot, vehicles in sorted(by_depot.items()):
        jobs = sum(v.jobs_done for v in vehicles)
        km = sum(v.driven_m for v in vehicles) / 1000
        kwh = sum(v.used_kwh for v in vehicles)
        use = sum(utilisation(v, day_minutes) for v in vehicles) / len(vehicles)
        lines.append(
            f"{depot}: {len(vehicles)} vehicles, {jobs} jobs, {km:.1f} km, "
            f"{kwh:.1f} kWh, utilisation {100 * use:.1f} %"
        )
    return lines
