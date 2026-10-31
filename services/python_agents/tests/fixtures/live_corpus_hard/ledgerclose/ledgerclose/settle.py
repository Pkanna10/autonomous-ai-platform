"""Settling transfers in the order they arrived."""


def settle(pending: list[tuple[int, int]]) -> tuple[dict[int, int], list[int]]:
    """Apply every pending transfer, first come first served.

    Returns the final balance per account (accounts in ascending order) and,
    for each transfer, the total held across all accounts once it settled.
    """
    accounts: list[int] = []
    balances: list[int] = []
    held: list[int] = []
    total = 0
    for account, amount in pending:
        try:
            slot = accounts.index(account)
        except ValueError:
            slot = len(accounts)
            accounts.append(account)
            balances.append(0)
        balances[slot] += amount
        total += amount
        held.append(total)
    return dict(sorted(zip(accounts, balances, strict=True))), held
