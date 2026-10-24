"""Final scores and the letter-grade export."""

from gradebook.letters import letter_for
from gradebook.scores import category_percent

WEIGHTS = {"homework": 0.4, "exams": 0.6}


def final_score(record, weights=WEIGHTS):
    """The weighted mean of the category percentages, to one decimal."""
    total = sum(w * category_percent(record[name]) for name, w in weights.items())
    return round(total, 1)


def letter_report(records, weights=WEIGHTS):
    """Every student's letter grade, by name."""
    return {
        name: letter_for(final_score(record, weights))
        for name, record in sorted(records.items())
    }
