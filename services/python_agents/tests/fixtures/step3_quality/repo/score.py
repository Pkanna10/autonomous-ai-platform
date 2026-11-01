"""The user's scorer: accuracy of the predictions on stdin against the labels."""

import sys

with open("data/labels.txt", encoding="utf-8") as handle:
    labels = handle.read().split()
predicted = sys.stdin.read().split()
hits = sum(p == q for p, q in zip(predicted, labels, strict=False))
print(f"aip-quality/1 accuracy={hits / len(labels)}")
