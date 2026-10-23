"""Deterministic posts: the same data on every run."""

from typing import NamedTuple


class Post(NamedTuple):
    number: int
    board: str
    topics: tuple[str, ...]


def _numbers(seed: int, count: int) -> list[int]:
    state = seed
    out: list[int] = []
    for _ in range(count):
        state = (state * 1103515245 + 12345) % (1 << 31)
        out.append(state >> 4)
    return out


def posts(count: int, labels: int) -> list[Post]:
    """``count`` posts, each with one to four of ``labels`` topic labels."""
    boards = ("general", "help", "showcase", "meta", "events")
    numbers = _numbers(13, count * 6)
    out: list[Post] = []
    for i in range(count):
        chunk = numbers[6 * i : 6 * i + 6]
        many = 1 + chunk[0] % 4
        topics = tuple(f"topic-{n % labels:05d}" for n in chunk[2 : 2 + many])
        out.append(Post(i, boards[chunk[1] % len(boards)], topics))
    return out
