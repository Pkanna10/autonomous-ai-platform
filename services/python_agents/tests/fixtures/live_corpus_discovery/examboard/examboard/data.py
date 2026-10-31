"""Deterministic candidates and marks: the same results on every run."""

import random


def candidates(count: int) -> list[str]:
    return [f"C{number:05d}" for number in range(count)]


def marks(exam: int, names: list[str]) -> list[tuple[int, str]]:
    """One exam's ``(mark out of 100, candidate)`` results."""
    drawn = random.Random(exam).choices(range(101), k=len(names))
    return list(zip(drawn, names, strict=True))
