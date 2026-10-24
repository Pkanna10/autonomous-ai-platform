"""Service levels per job and per customer tier."""

from dataclasses import dataclass

from fleetsim.metrics import share_at_most
from fleetsim.simulation import Outcome


@dataclass(frozen=True)
class JobService:
    number: int
    tier: str
    wait: float
    standing: float  # share of past waits at most as long as this one


def per_job(outcomes: list[Outcome], past: list[float]) -> list[JobService]:
    """Each delivered job with its standing among the ``past`` waits."""
    return [
        JobService(
            outcome.job.number,
            outcome.job.tier,
            outcome.wait,
            share_at_most(past, outcome.wait),
        )
        for outcome in outcomes
    ]


def on_time_by_tier(outcomes: list[Outcome]) -> dict[str, tuple[int, int]]:
    """``(on time, delivered)`` per tier, tiers sorted."""
    counts: dict[str, list[int]] = {}
    for outcome in outcomes:
        row = counts.setdefault(outcome.job.tier, [0, 0])
        row[0] += outcome.on_time
        row[1] += 1
    return {tier: (row[0], row[1]) for tier, row in sorted(counts.items())}


def worst_standing(services: list[JobService], tier: str, count: int) -> list[int]:
    """The job numbers of ``tier`` with the highest standing (the longest
    waits relative to everyone), ties by number."""
    chosen = [s for s in services if s.tier == tier]
    chosen.sort(key=lambda s: (-s.standing, s.number))
    return [s.number for s in chosen[:count]]
