"""Shifts to staff."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Shift:
    day: str
    skill: str
