"""Deterministic club members: the same roster on every run."""

from typing import NamedTuple

PARTS = ("an", "Bel", "cor", "Dun", "el", "Far", "gil", "Hal", "is", "Mor", "ok", "Ven")
GIVEN = (
    "Ada",
    "ben",
    "Cleo",
    "dev",
    "Eli",
    "fay",
    "Gus",
    "ivy",
    "Jon",
    "kit",
    "Lou",
    "max",
)
TEAMS = ("red", "blue", "green", "gold", "white")


class Member(NamedTuple):
    number: int
    surname: str
    given: str
    points: int
    team: str


def members(count: int) -> list[Member]:
    state = 3
    crowd: list[Member] = []
    for number in range(1, count + 1):
        state = (state * 1103515245 + 12345) % (1 << 31)
        surname = (
            PARTS[state % 12] + PARTS[state >> 4 & 7].lower() + PARTS[state >> 7 & 7]
        )
        crowd.append(
            Member(
                number,
                surname,
                GIVEN[state >> 10 & 7],
                state >> 13 & 127,
                TEAMS[state % 5],
            )
        )
    return crowd
