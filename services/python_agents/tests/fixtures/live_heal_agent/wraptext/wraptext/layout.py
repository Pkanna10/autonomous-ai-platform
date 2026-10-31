"""Paragraph layout."""

from wraptext.wrap import wrap


def paragraph(text, width, indent=""):
    """``text`` wrapped to ``width`` columns, every line starting with
    ``indent`` (which counts towards the width)."""
    return "\n".join(indent + line for line in wrap(text, width - len(indent)))
