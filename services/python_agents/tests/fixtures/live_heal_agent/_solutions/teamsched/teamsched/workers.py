"""Workers, the days they work and the skills they have."""

from dataclasses import dataclass

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def parse_days(text):
    """Days written as a list such as "mon,wed" or a range such as "mon-fri"
    (both ends included), or a mix: "mon-wed,sat"."""
    days = set()
    for part in text.split(","):
        part = part.strip()
        if "-" in part:
            first, last = part.split("-")
            days.update(DAYS[DAYS.index(first) : DAYS.index(last) + 1])
        else:
            days.add(part)
    return days


@dataclass(frozen=True)
class Worker:
    name: str
    days: frozenset
    skills: frozenset


def worker(name, days, skills):
    """A worker from text: ``days`` for ``parse_days``, ``skills`` as "bar,floor"."""
    return Worker(name, frozenset(parse_days(days)), frozenset(skills.split(",")))
