"""The workload: ``python -m slowsum.main [COUNT]``. Prints one line."""

import sys

from slowsum.core import common_count


def values(count: int, seed: int) -> list[int]:
    """``count`` deterministic integers in ``[0, 4 * count)``."""
    state, out = seed, []
    for _ in range(count):
        state = (state * 1103515245 + 12345) % (1 << 31)
        out.append(state % (4 * count))
    return out


def main(argv: list[str]) -> int:
    count = int(argv[0]) if argv else 8000
    print(f"common={common_count(values(count, 1), values(count, 2))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
