"""Tests for the live event log (Step 1, unit U4).

``emit`` streams an ``EngineEvent`` through LangGraph's custom stream when a
graph is running and falls back to structlog otherwise. It never raises.
"""

from __future__ import annotations

from datetime import UTC
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from structlog.testing import capture_logs

from autonomous_ai_agents.common.models import (
    EngineEvent,
    EventLevel,
    RunPhase,
    ScalarDict,
)
from autonomous_ai_agents.orchestrator.events import emit, make_event


class _RunState(TypedDict):
    run_id: str


def _graph_emitting(
    event: EngineEvent,
) -> CompiledStateGraph[_RunState, None, _RunState, _RunState]:
    def node(state: _RunState) -> dict[str, str]:
        emit(event)
        return {"run_id": state["run_id"]}

    graph: StateGraph[_RunState, None, _RunState, _RunState] = StateGraph(_RunState)
    graph.add_node("emitter", node)
    graph.add_edge(START, "emitter")
    graph.add_edge("emitter", END)
    return graph.compile()


# ---------------------------------------------------------------------------
# make_event
# ---------------------------------------------------------------------------


def test_make_event_defaults_to_info_with_empty_data() -> None:
    """
    GIVEN only run_id, phase and message
    WHEN make_event builds an event
    THEN level is info, data is empty and the timestamp is tz-aware UTC
    """
    event = make_event("run-1", RunPhase.baseline, "5 runs -> 1.80 s")

    assert event.run_id == "run-1"
    assert event.phase is RunPhase.baseline
    assert event.message == "5 runs -> 1.80 s"
    assert event.level is EventLevel.info
    assert event.data == {}
    assert event.at.tzinfo is UTC


def test_make_event_copies_level_and_data() -> None:
    """
    GIVEN a level and a data dict
    WHEN make_event builds an event and the caller mutates the dict afterwards
    THEN the event keeps the level and its own copy of the data
    """
    data: ScalarDict = {"n": 5, "mean": 1.8}

    event = make_event(
        "run-1", RunPhase.trials, "trial failed", level=EventLevel.error, data=data
    )
    data["n"] = 99

    assert event.level is EventLevel.error
    assert event.data == {"n": 5, "mean": 1.8}


# ---------------------------------------------------------------------------
# emit outside a graph
# ---------------------------------------------------------------------------


def test_emit_outside_graph_does_not_raise() -> None:
    """
    GIVEN no running graph
    WHEN emit is called
    THEN it returns normally
    """
    emit(make_event("run-1", RunPhase.connect, "hello"))


def test_emit_outside_graph_logs_through_structlog() -> None:
    """
    GIVEN no running graph
    WHEN emit is called
    THEN the event's JSON fields are logged as one structlog entry
    """
    event = make_event(
        "run-1", RunPhase.connect, "hello", level=EventLevel.warning, data={"k": 1}
    )

    with capture_logs() as logs:
        emit(event)

    assert logs == [
        {"event": "engine_event", "log_level": "info", **event.model_dump(mode="json")}
    ]


# ---------------------------------------------------------------------------
# emit inside a graph
# ---------------------------------------------------------------------------


def test_emit_inside_graph_streams_the_event_as_custom_chunk() -> None:
    """
    GIVEN a graph whose node emits one event
    WHEN the graph is streamed in custom mode
    THEN the only chunk is the event dumped as JSON-compatible dict
    """
    event = make_event("run-1", RunPhase.research, "3 techniques", data={"n": 3})
    graph = _graph_emitting(event)

    chunks = list(graph.stream({"run_id": "run-1"}, stream_mode="custom"))

    assert chunks == [event.model_dump(mode="json")]
    assert chunks[0]["phase"] == "research"
    assert isinstance(chunks[0]["at"], str)


def test_emit_inside_graph_appears_in_multi_mode_stream() -> None:
    """
    GIVEN a graph whose node emits one event
    WHEN the graph is streamed in ["custom", "updates"] mode (the CLI's mode)
    THEN the event arrives tagged "custom" before the node's update
    """
    event = make_event("run-1", RunPhase.research, "3 techniques")
    graph = _graph_emitting(event)

    chunks = list(graph.stream({"run_id": "run-1"}, stream_mode=["custom", "updates"]))

    custom, update = chunks

    assert custom == ("custom", event.model_dump(mode="json"))
    assert isinstance(update, tuple)
    assert update[0] == "updates"


def test_emit_inside_graph_does_not_fall_back_to_structlog() -> None:
    """
    GIVEN a graph whose node emits one event
    WHEN the graph is invoked (no custom stream consumer)
    THEN the event is neither raised on nor logged through structlog
    """
    graph = _graph_emitting(make_event("run-1", RunPhase.research, "quiet"))

    with capture_logs() as logs:
        result = graph.invoke({"run_id": "run-1"})

    assert result == {"run_id": "run-1"}
    assert logs == []
