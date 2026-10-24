"""The handler registry: which functions run when an event is published."""

HANDLERS = {}  # event name -> the handlers subscribed to it, in order


def on(event):
    """Subscribe the decorated function to ``event`` (a name such as
    "order.paid"); one event can have several handlers, run in the order
    they were registered."""

    def register(func):
        HANDLERS.setdefault(func.__name__, []).append(func)
        return func

    return register


def handlers_for(event):
    """The handlers subscribed to ``event``, in registration order."""
    return list(HANDLERS.get(event, ()))
