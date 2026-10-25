"""Classification metrics."""


def recall(rows, predictions, label):
    """The share of the rows labelled ``label`` that were predicted as it."""
    relevant = [
        p for row, p in zip(rows, predictions, strict=True) if row["label"] == label
    ]
    hits = sum(1 for p in relevant if p == label)
    return hits / len(relevant)
