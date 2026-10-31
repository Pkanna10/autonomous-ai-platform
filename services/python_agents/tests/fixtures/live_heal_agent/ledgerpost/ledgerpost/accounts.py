"""The chart of accounts."""

ACCOUNTS = {"cash", "bank", "sales", "rent", "supplies"}


class UnknownAccountError(KeyError):
    """The entry names an account the chart does not have."""


def require(account):
    if account not in ACCOUNTS:
        raise UnknownAccountError(account)
    return account
