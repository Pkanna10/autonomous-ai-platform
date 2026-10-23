"""Matching records against the allowlist."""


def matches(tags: list[str], allowed: list[str]) -> bool:
    """True when any of ``tags`` is in ``allowed``."""
    for tag in tags:
        if tag in allowed:
            return True
    return False


def count_by_kind(
    records: list[tuple[str, list[str]]], allowed: list[str]
) -> dict[str, int]:
    """How many records of each kind match, kinds in sorted order."""
    counts: dict[str, int] = {}
    for kind, tags in records:
        counts.setdefault(kind, 0)
        if matches(tags, allowed):
            counts[kind] += 1
    return dict(sorted(counts.items()))
