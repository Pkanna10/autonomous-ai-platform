"""Deterministic transfers: the same data on every run."""


def _numbers(seed: int, count: int) -> list[int]:
    state = seed
    out: list[int] = []
    for _ in range(count):
        state = (state * 1103515245 + 12345) % (1 << 31)
        out.append(state >> 4)
    return out


def transfers(count: int, accounts: int) -> list[tuple[int, int]]:
    """``count`` transfers of ``(account number, amount in cents)``; account
    numbers run from 10000 and amounts may be negative (a withdrawal)."""
    numbers = _numbers(23, 2 * count)
    out: list[tuple[int, int]] = []
    for i in range(count):
        who, cents = numbers[2 * i], numbers[2 * i + 1]
        out.append((10000 + who % accounts, cents % 20001 - 9000))
    return out
