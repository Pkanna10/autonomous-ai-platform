"""A deterministic day of catalogue updates and browsing."""

SYLLABLES = ("ka", "lo", "mi", "ra", "ten", "su", "vo", "di", "ne", "par", "go", "lin")


def _word(number: int) -> str:
    first, second, third = number % 12, number // 12 % 12, number // 144 % 12
    return (SYLLABLES[first] + SYLLABLES[second] + SYLLABLES[third]).capitalize()


def day(titles: int, commands: int) -> tuple[list[str], list[tuple[str, str]]]:
    """``titles`` starting titles and ``commands`` actions: ``("add", title)``
    or ``("list", prefix)``."""
    state = 17
    made: list[str] = []
    actions: list[tuple[str, str]] = []
    while len(actions) < commands:
        state = (state * 1103515245 + 12345) % (1 << 31)
        title = f"{_word(state >> 4)} {_word(state >> 14)}, part {state % 9 + 1}"
        if len(made) < titles:
            made.append(title)
        elif state % 5 < 2:
            actions.append(("add", title))
        else:
            actions.append(("list", title[:3]))
    return made, actions
