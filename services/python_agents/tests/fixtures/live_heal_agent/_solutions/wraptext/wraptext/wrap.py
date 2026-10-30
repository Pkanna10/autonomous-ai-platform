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
        pieces = [word[i : i + width] for i in range(0, len(word), width)]
        for piece in pieces:
            candidate = f"{current} {piece}" if current else piece
            if len(candidate) <= width:
                current = candidate
            else:
                lines.append(current)
                current = piece
    if current:
        lines.append(current)
    return lines
