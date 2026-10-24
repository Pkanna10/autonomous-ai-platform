"""Deterministic records and allowlist: the same data on every run."""


def _numbers(seed: int, count: int) -> list[int]:
    state = seed
    out: list[int] = []
    for _ in range(count):
        state = (state * 1103515245 + 12345) % (1 << 31)
        out.append(state >> 4)
    return out


def allowlist(size: int) -> list[str]:
    """``size`` tag names, in the order the policy file would list them."""
    return [f"tag-{n % 90000:05d}" for n in _numbers(17, size)]


def records(count: int, tags_each: int) -> list[tuple[str, list[str]]]:
    """``count`` records of ``(kind, tags)``."""
    kinds = ("invoice", "receipt", "refund", "quote")
    numbers = _numbers(41, count * (tags_each + 1))
    out: list[tuple[str, list[str]]] = []
    for i in range(count):
        chunk = numbers[i * (tags_each + 1) : (i + 1) * (tags_each + 1)]
        kind = kinds[chunk[0] % len(kinds)]
        out.append((kind, [f"tag-{n % 90000:05d}" for n in chunk[1:]]))
    return out
