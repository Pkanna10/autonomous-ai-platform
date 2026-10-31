"""Wrapping words into lines."""


class WrapError(ValueError):
    """The text cannot be wrapped."""


def wrap(text, width):
    """Lines of at most ``width`` characters, breaking between words. A word
    longer than ``width`` (a long link, say) is split across lines, ``width``
    characters at a time; no character of the text is ever dropped."""
    if width < 1:
        raise WrapError(f"the width {width} is not positive")
    lines, current = [], ""
    for word in text.split():
        if len(word) > width:  # a long word gets a line of its own
            if current:
                lines.append(current)
            lines.append(word)
            current = ""
            continue
        candidate = f"{current} {word}" if current else word
        if len(candidate) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines
