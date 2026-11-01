"""The request limiter."""

from quotas.config import parse_duration
from quotas.window import Window


class QuotaExceededError(RuntimeError):
    """The client made its quota of requests in the window already."""


class Limiter:
    def __init__(self, limit, window):
        """At most ``limit`` requests per client in any ``window``, a
        duration such as "30s" or "1m"."""
        self.limit = limit
        self.window = window
        self.length = parse_duration(window) / 1000  # the window counts seconds
        self.windows = {}

    def acquire(self, client, now):
        """Admit one request from ``client`` at time ``now`` (in seconds), or
        refuse it when the client's quota for the window is used up."""
        window = self.windows.setdefault(client, Window(self.length))
        window.prune(now)
        if len(window) >= self.limit:
            raise QuotaExceededError(
                f"client {client!r} made {len(window)} requests in the last "
                f"{self.window}"
            )
        window.add(now)
