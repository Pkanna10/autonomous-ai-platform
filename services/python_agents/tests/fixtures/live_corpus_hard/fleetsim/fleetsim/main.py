"""Workload: ``python -m fleetsim.main``."""

from fleetsim.checks import check_fleet, check_outcomes
from fleetsim.feed import jobs, past_waits, vehicles
from fleetsim.report import fleet_section, tiers_section, waits_section
from fleetsim.simulation import run_day
from fleetsim.tariffs import check_bands, cost_by_band
from fleetsim.timeline import jobs_per_hour, mean_wait_per_hour, peak_hour, sparkline

DAY_MINUTES = 16 * 60.0
START_HOUR = 6


def main() -> None:
    check_bands()
    fleet = vehicles(5)
    offered = jobs(1500, DAY_MINUTES)
    day = run_day(fleet, offered, DAY_MINUTES)
    print(f"events {day.events}")
    for line in waits_section(day):
        print(line)
    for line in tiers_section(day, past_waits(3500)):
        print(line)
    for line in fleet_section(fleet, DAY_MINUTES):
        print(line)
    counts = jobs_per_hour(day.outcomes, START_HOUR)
    waits = mean_wait_per_hour(day.outcomes, START_HOUR)
    print(f"peak hour {peak_hour(counts)}:00")
    print("demand |" + sparkline([float(c) for c in counts.values()]) + "|")
    print("waits  |" + sparkline(list(waits.values())) + "|")
    sessions = [
        (START_HOUR * 60 + v.busy_minutes % DAY_MINUTES, 45.0, v.used_kwh / 4)
        for v in fleet
    ]
    costs = cost_by_band(sessions)
    print("charging " + " ".join(f"{band}={cents}" for band, cents in costs.items()))
    problems = check_outcomes(day, offered) + check_fleet(fleet)
    print(f"checks {len(problems)} problem(s)")


if __name__ == "__main__":
    main()
