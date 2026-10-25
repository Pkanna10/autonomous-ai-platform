"""Points per category, as percentages."""


def category_percent(items):
    """The percentage a student scored in one category: the points of all
    its items over their total maximum, times 100. Items can be worth
    different maximums (a 10-point quiz and a 50-point exam)."""
    if not items:
        raise ValueError("a category needs at least one item")
    points = sum(item["points"] for item in items)
    maximum = sum(item["max"] for item in items)
    return 100 * points / maximum
