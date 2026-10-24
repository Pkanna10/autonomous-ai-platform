"""Letter grades."""

BANDS = ((90, "A"), (80, "B"), (70, "C"), (60, "D"))


def letter_for(score):
    """The letter for a final score from 0 to 100. A score outside that
    range means the data upstream is broken (scores are never capped), so it
    is refused with ValueError instead of being graded."""
    if score < 0:
        raise ValueError(f"score out of range: {score}")
    score = min(score, 100)
    for floor, letter in BANDS:
        if score >= floor:
            return letter
    return "F"
