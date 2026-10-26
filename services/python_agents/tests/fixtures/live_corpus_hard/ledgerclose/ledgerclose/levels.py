"""Levels of a series of totals."""


def level_numbers(values: list[int], step: int) -> list[int]:
    """For each position, the number of its level (``value // step``), the
    levels numbered from 1 in the order the series first reaches them."""
    if step < 1:
        raise ValueError("step must be at least 1")
    reached: list[int] = []
    numbers: list[int] = []
    for value in values:
        level = value // step
        try:
            number = reached.index(level) + 1
        except ValueError:
            reached.append(level)
            number = len(reached)
        numbers.append(number)
    return numbers
