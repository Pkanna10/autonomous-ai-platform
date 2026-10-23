"""Pending pickups, lowest cost first."""


def pending_views(
    offers: list[tuple[int, str]], every: int, show: int
) -> list[list[tuple[int, str]]]:
    """Feed ``offers`` (cost, stop code) one at a time into the pending list
    kept in ascending order; every ``every`` offers, record the ``show``
    lowest-cost pending ones."""
    pending: list[tuple[int, str]] = []
    views: list[list[tuple[int, str]]] = []
    for count, offer in enumerate(offers, start=1):
        pending = sorted([*pending, offer])
        if count % every == 0:
            views.append(pending[:show])
    return views
