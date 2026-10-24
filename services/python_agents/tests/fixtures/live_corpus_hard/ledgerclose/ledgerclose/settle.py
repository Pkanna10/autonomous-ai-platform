"""Settling transfers in the order they arrived."""


def settle(pending: list[tuple[str, int]]) -> tuple[dict[str, int], list[int]]:
    """Apply every pending transfer, first come first served.

    Returns the final balance per account (accounts in sorted order) and,
    for each transfer, the total held across all accounts once it settled.
    """
    queue = list(pending)
    balances: dict[str, int] = {}
    held: list[int] = []
    total = 0
    while queue:
        account, amount = queue.pop(0)
        balances[account] = balances.get(account, 0) + amount
        total += amount
        held.append(total)
    return dict(sorted(balances.items())), held
