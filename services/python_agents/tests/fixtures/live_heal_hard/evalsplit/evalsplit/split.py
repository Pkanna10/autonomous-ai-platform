"""Train/test splits."""

import random
from collections import Counter


def train_test_split(rows, test_fraction=0.25, seed=None):
    """Split labelled rows (dicts with a "label") into ``(train, test)``.

    The split is stratified: every label appears in both parts, so each
    label needs at least two rows (ValueError otherwise). ``seed`` makes the
    split reproducible; without one every call shuffles differently.
    """
    counts = Counter(row["label"] for row in rows)
    if any(count < 2 for count in counts.values()):
        raise ValueError("every label needs at least two rows")
    rng = random.Random(seed)
    shuffled = list(rows)
    rng.shuffle(shuffled)
    cut = max(1, round(len(shuffled) * test_fraction))
    return shuffled[cut:], shuffled[:cut]
