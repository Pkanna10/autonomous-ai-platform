"""A deterministic log and watch list."""

SYLLABLES = ("ka", "lo", "mi", "ne", "ru", "sa", "to", "vi", "ze", "po")
LEVELS = ("INFO", "WARN", "ERROR")


def _numbers(seed: int, count: int) -> list[int]:
    state = seed
    out: list[int] = []
    for _ in range(count):
        state = (state * 1103515245 + 12345) % (1 << 31)
        out.append(state >> 3)
    return out


def _word(n: int) -> str:
    return SYLLABLES[n % 10] + SYLLABLES[(n // 10) % 10] + SYLLABLES[(n // 100) % 10]


def watch_list(size: int) -> list[str]:
    """``size`` keywords, as an operator would paste them."""
    return [_word(n) for n in _numbers(5, size)]


def log_lines(count: int, words_each: int) -> list[tuple[str, str]]:
    """``count`` lines of ``(level, text)``."""
    numbers = _numbers(23, count * (words_each + 1))
    lines: list[tuple[str, str]] = []
    for i in range(count):
        chunk = numbers[i * (words_each + 1) : (i + 1) * (words_each + 1)]
        level = LEVELS[chunk[0] % len(LEVELS)]
        lines.append((level, " ".join(_word(n) for n in chunk[1:])))
    return lines
