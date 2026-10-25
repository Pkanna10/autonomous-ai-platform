"""Publishing events to their handlers."""

from eventbus.registry import HANDLERS


class UnknownEventError(LookupError):
    """Nothing listens to the event: almost always a typo in its name."""


def publish(event, payload):
    """Run every handler subscribed to ``event`` with ``payload`` and return
    their results in order. Publishing an event that no handler listens to is
    a programming error (a misspelt name would otherwise be lost silently),
    so it raises ``UnknownEventError``."""
    try:
        handlers = HANDLERS[event]
    except KeyError:
        raise UnknownEventError(f"no handler listens to {event!r}") from None
    return [handler(payload) for handler in handlers]
