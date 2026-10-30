"""Statistics of one numeric column of a CSV export."""

from csvstats.reader import read_rows
from csvstats.stats import mean, median


def column_values(text, column):
    return [float(row[column]) for row in read_rows(text)]


def column_summary(text, column):
    """The mean and the median of ``column``."""
    values = column_values(text, column)
    return {"mean": mean(values), "median": median(values)}
