"""Did-you-mean suggestions for query words the index does not hold."""


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance between ``a`` and ``b`` (two-row dynamic
    programming)."""
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (ca != cb),
                )
            )
        previous = current
    return previous[-1]


def suggestions(word: str, vocabulary: list[str], limit: int = 3) -> list[str]:
    """Up to ``limit`` vocabulary terms closest to ``word`` (distance at most
    two), closest first, ties alphabetical."""
    scored = []
    for term in vocabulary:
        if abs(len(term) - len(word)) > 2:
            continue
        distance = edit_distance(word, term)
        if distance <= 2:
            scored.append((distance, term))
    scored.sort()
    return [term for _, term in scored[:limit]]


def unknown_words(words: list[str], vocabulary: set[str]) -> list[str]:
    """The ``words`` the vocabulary lacks, first appearance order, once each."""
    seen: dict[str, None] = {}
    for word in words:
        if word not in vocabulary:
            seen[word] = None
    return list(seen)
