"""A scorer whose number depends on str hashing and set order (a U19 fixture)."""

import sys

sys.stdin.read()
first = next(iter({"alpha", "beta", "gamma", "delta", "epsilon"}))
print(f"aip-quality/1 acc={hash('abc') % 997 + len(first) / 10}")
