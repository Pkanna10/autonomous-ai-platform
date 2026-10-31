"""Summary statistics."""


def mean(values):
    values = list(values)
    return sum(values) / len(values)


def median(values):
    """The middle value, or the mean of the two middle values when there is
    an even number of them."""
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle] + ordered[middle + 1]) / 2
