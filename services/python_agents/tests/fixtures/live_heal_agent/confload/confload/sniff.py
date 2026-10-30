"""Guessing a delimited text's delimiter."""

DELIMITERS = (",", ";", "|", "\t")


def sniff(text):
    """The delimiter of ``text``: whichever of , ; | and tab occurs most often
    in its first line (a comma when none does; ties go to the earlier one)."""
    first = text.splitlines()[0] if text else ""
    counts = {d: first.count(d) for d in DELIMITERS}
    best = max(DELIMITERS, key=lambda d: counts[d])
    return best if counts[best] else ","
