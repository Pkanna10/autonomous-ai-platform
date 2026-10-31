"""A sliding window of event times."""

from collections import deque


class Window:
    """The times (in seconds) of the events of the last ``length`` seconds."""

    def __init__(self, length):
        self.length = length
        self.times = deque()

    def prune(self, now):
        """Forget the events older than ``length`` seconds at time ``now``."""
        while self.times and self.times[0] <= now - self.length:
            self.times.popleft()

    def add(self, now):
        self.times.append(now)

    def __len__(self):
        return len(self.times)
