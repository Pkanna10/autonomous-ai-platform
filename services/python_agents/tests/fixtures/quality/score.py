"""Accuracy of the predictions on stdin against labels.txt (a U19 fixture)."""

import sys

with open("labels.txt", encoding="utf-8") as handle:
    labels = handle.read().split()
predictions = sys.stdin.read().split()
hits = sum(p == q for p, q in zip(predictions, labels, strict=False))
print(f"aip-quality/1 acc={hits / len(labels)}")
