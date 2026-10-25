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
    train, test = [], []
    for label in sorted(counts):
        group = [row for row in rows if row["label"] == label]
        rng.shuffle(group)
        cut = min(len(group) - 1, max(1, round(len(group) * test_fraction)))
        test.extend(group[:cut])
        train.extend(group[cut:])
    return train, test
