"""Fair shares of a total."""


class SplitError(ArithmeticError):
    """The shares do not add up to the total."""


def split_evenly(total, people):
    """Split ``total`` cents among ``people``: the shares add up to the total
    exactly and differ by at most one cent; the first people in the list pay
    the extra cents."""
    share, extra = divmod(total, people)
    shares = [share + 1] * extra + [share] * (people - extra)
    if sum(shares) != total:
        raise SplitError(f"shares add up to {sum(shares)}, not {total}")
    return shares
