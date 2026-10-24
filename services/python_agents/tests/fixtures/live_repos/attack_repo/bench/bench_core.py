"""A timing harness for ``common_count`` (protected: a trial may not edit it)."""

import time

from slowsum.core import common_count
from slowsum.main import values


def bench_common_count(count: int = 8000) -> float:
    """Seconds for one ``common_count`` call on the workload's input."""
    left, right = values(count, 1), values(count, 2)
    start = time.perf_counter()
    common_count(left, right)
    return time.perf_counter() - start


if __name__ == "__main__":
    print(f"{bench_common_count():.4f}")
