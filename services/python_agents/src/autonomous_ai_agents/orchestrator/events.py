"""Live log of an engine run.

Nodes call ``emit`` with an ``EngineEvent``. Inside a running graph the event
goes to LangGraph's custom stream, so a consumer using
``graph.stream(..., stream_mode="custom")`` (or ``["custom", "updates"]``)
sees it as it happens. Outside a graph (unit tests, scripts) there is no
stream writer, so the event is logged through structlog instead. ``emit``
never raises: a lost log line must not fail a run.
"""

from __future__ import annotations

import structlog
from langgraph.config import get_stream_writer

from autonomous_ai_agents.common.models import (
    EngineEvent,
    EventLevel,
    RunPhase,
    ScalarDict,
)


def make_event(
    run_id: str,
    phase: RunPhase,
    message: str,
    *,
    level: EventLevel = EventLevel.info,
    data: ScalarDict | None = None,
) -> EngineEvent:
    """Build an ``EngineEvent`` stamped now, copying ``data`` so it stays frozen."""
    return EngineEvent(
        run_id=run_id,
        phase=phase,
        level=level,
        message=message,
        data=dict(data) if data is not None else {},
    )


def emit(event: EngineEvent) -> None:
    """Send ``event`` to the graph's custom stream, or log it when no graph runs."""
    payload = event.model_dump(mode="json")
    try:
        writer = get_stream_writer()
    except RuntimeError:
        structlog.get_logger().info("engine_event", **payload)
        return
    writer(payload)
