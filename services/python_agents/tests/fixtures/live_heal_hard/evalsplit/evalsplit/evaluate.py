"""Evaluating a classifier on a held-out split."""

from evalsplit.metrics import recall
from evalsplit.split import train_test_split


def evaluate(rows, predict, test_fraction=0.25, seed=None):
    """Recall per label (every label in ``rows``) of ``predict`` on the
    test part of a stratified split, to three decimals."""
    _, test = train_test_split(rows, test_fraction, seed)
    predictions = [predict(row) for row in test]
    labels = sorted({row["label"] for row in rows})
    return {label: round(recall(test, predictions, label), 3) for label in labels}
