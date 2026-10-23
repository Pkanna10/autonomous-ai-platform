"""The simulation's agenda: events kept in time order."""

from bisect import insort
from dataclasses import dataclass, field


@dataclass(frozen=True, order=True)
class Event:
    at: float
    sequence: int
    kind: str = field(compare=False)
    subject: int = field(compare=False)


class Agenda:
    """Events in time order; equal times keep the order they were added in."""

    def __init__(self) -> None:
        self._events: list[Event] = []
        self._sequence = 0

    def add(self, at: float, kind: str, subject: int) -> Event:
        event = Event(at, self._sequence, kind, subject)
        self._sequence += 1
        insort(self._events, event)
        return event

    def next(self) -> Event:
        if not self._events:
            raise IndexError("the agenda is empty")
        return self._events.pop(0)

    def __len__(self) -> int:
        return len(self._events)

    def peek_time(self) -> float | None:
        return self._events[0].at if self._events else None

    def kinds(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for event in self._events:
            counts[event.kind] = counts.get(event.kind, 0) + 1
        return dict(sorted(counts.items()))
