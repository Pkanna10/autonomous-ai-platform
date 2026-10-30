"""Assigning workers to shifts."""

from teamsched.workers import DAYS


class NoEligibleWorkerError(LookupError):
    """No worker works that day with the skill the shift needs."""


def assign(workers, shifts):
    """Give every shift to the eligible worker (one who works that day and
    has the skill) with the fewest shifts so far; ties go by name. Shifts are
    planned in week order, then by skill."""
    load = {w.name: 0 for w in workers}
    plan = {}
    for shift in sorted(shifts, key=lambda s: (DAYS.index(s.day), s.skill)):
        eligible = [
            w for w in workers if shift.day in w.days and shift.skill in w.skills
        ]
        if not eligible:  # fall back to anyone with the skill
            eligible = [w for w in workers if shift.skill in w.skills]
        if not eligible:
            raise NoEligibleWorkerError(
                f"no one can work {shift.skill!r} on {shift.day!r}"
            )
        chosen = min(eligible, key=lambda w: (load[w.name], w.name))
        load[chosen.name] += 1
        plan[shift] = chosen.name
    return plan
