"""Tests for the engine state (Step 1, unit U4).

``EngineState`` is the TypedDict LangGraph checkpoints between nodes.
``initial_state`` must set every key, because LangGraph drops unset keys from
the dict a node receives, and exactly four channels are append-only reducers
that nodes feed with deltas.
"""

from __future__ import annotations

import operator
import re
import uuid
from typing import get_type_hints

import pytest
from langgraph.graph import END, START, StateGraph

from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.models import (
    METRIC_WALL_TIME_S,
    Direction,
    EngineEvent,
    Guardrail,
    GuardrailKind,
    Objective,
    ObjectiveKind,
    Project,
    RunPhase,
    Workload,
)
from autonomous_ai_agents.orchestrator.state import (
    REDUCER_KEYS,
    RUN_ID_PATTERN,
    AgentState,
    EngineState,
    initial_state,
    validate_run_id,
)

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _project() -> Project:
    return Project(name="bridge", root_path="/home/dev/bridge")


def _workload(project: Project) -> Workload:
    return Workload(project_id=project.id, name="train", command=("python", "train.py"))


def _objective(project: Project) -> Objective:
    return Objective(
        project_id=project.id,
        kind=ObjectiveKind.runtime,
        metric=METRIC_WALL_TIME_S,
        direction=Direction.minimize,
        description="minimize seconds per training step",
    )


def _guardrail(project: Project) -> Guardrail:
    return Guardrail(
        project_id=project.id,
        kind=GuardrailKind.tests_pass,
        description="existing tests must pass",
    )


def _state(*, run_id: str | None = None, max_rounds: int | None = None) -> EngineState:
    project = _project()
    return initial_state(
        project,
        [_workload(project)],
        [_objective(project)],
        [_guardrail(project)],
        run_id=run_id,
        max_rounds=max_rounds,
    )


# ---------------------------------------------------------------------------
# initial_state
# ---------------------------------------------------------------------------


def test_initial_state_sets_every_annotated_key() -> None:
    """
    GIVEN the EngineState schema
    WHEN initial_state builds a state
    THEN every annotated key is present, so nodes never need ``.get``
    """
    state = _state()

    assert set(EngineState.__annotations__) == set(state)
    assert len(state) == 25
    assert "round_trials" in state


def test_initial_state_defaults() -> None:
    """
    GIVEN no overrides
    WHEN initial_state builds a state
    THEN scalars, Nones and empty lists hold the documented defaults
    """
    state = _state()

    assert state["phase"] is RunPhase.connect
    assert state["round"] == 0
    assert state["max_rounds"] == settings.MAX_TRIAL_ROUNDS
    assert uuid.UUID(state["run_id"]).version == 4
    assert state["baseline"] is None
    assert state["approval"] is None
    assert state["delivery"] is None
    assert state["error"] is None
    assert state["tokens_used"] == 0
    assert state["cost_usd"] == 0.0
    for key in (
        "hotspots",
        "techniques",
        "papers",
        "hypotheses",
        "trials",
        "round_trials",
        "verdicts",
        "pending_approval_ids",
        "kept_verdict_ids",
        "lessons",
        "events",
    ):
        assert state[key] == [], key


def test_initial_state_keeps_project_and_inputs() -> None:
    """
    GIVEN a project, workloads, objectives and guardrails
    WHEN initial_state builds a state
    THEN the project is stored as is and the sequences become equal lists
    """
    project = _project()
    workload, objective, guardrail = (
        _workload(project),
        _objective(project),
        _guardrail(project),
    )

    state = initial_state(project, (workload,), (objective,), (guardrail,))

    assert state["project"] is project
    assert state["workloads"] == [workload]
    assert state["objectives"] == [objective]
    assert state["guardrails"] == [guardrail]


def test_initial_state_copies_input_sequences() -> None:
    """
    GIVEN lists passed to initial_state
    WHEN the caller mutates them afterwards
    THEN the state's lists are unaffected (fresh copies)
    """
    project = _project()
    workloads = [_workload(project)]
    objectives = [_objective(project)]
    guardrails = [_guardrail(project)]

    state = initial_state(project, workloads, objectives, guardrails)
    workloads.clear()
    objectives.clear()
    guardrails.clear()

    assert len(state["workloads"]) == 1
    assert len(state["objectives"]) == 1
    assert len(state["guardrails"]) == 1
    assert state["workloads"] is not workloads


def test_initial_state_honours_run_id_and_max_rounds_overrides() -> None:
    """
    GIVEN an explicit run_id and max_rounds
    WHEN initial_state builds a state
    THEN both override the defaults
    """
    state = _state(run_id="run-42", max_rounds=7)

    assert state["run_id"] == "run-42"
    assert state["max_rounds"] == 7


@pytest.mark.parametrize("max_rounds", [0, -1])
def test_initial_state_rejects_fewer_than_one_round(max_rounds: int) -> None:
    """
    GIVEN max_rounds below 1
    WHEN initial_state builds a state
    THEN a ValueError says a run needs at least one round
    """
    with pytest.raises(ValueError, match="max_rounds"):
        _state(max_rounds=max_rounds)


def test_initial_state_validates_the_run_id() -> None:
    """
    GIVEN a run id that cannot name a git branch or thread safely
    WHEN initial_state builds a state
    THEN a ValueError names the run id; a generated uuid4 always passes
    """
    with pytest.raises(ValueError, match="run_id"):
        _state(run_id="../../main")

    generated = _state()["run_id"]
    assert validate_run_id(generated) == generated


@pytest.mark.parametrize(
    "run_id",
    [
        "a",
        "run-42",
        "bridge.nightly_2026-10-21",
        "A" * 64,
        "0b9d4c1e-7f3a-4e2b-9c5d-6a8f1e2d3c4b",
    ],
)
def test_validate_run_id_accepts_refname_safe_ids(run_id: str) -> None:
    """
    GIVEN a run id of 1-64 letters, digits, dots, dashes or underscores that
          starts with a letter or digit
    WHEN validate_run_id checks it
    THEN it is returned unchanged and matches RUN_ID_PATTERN
    """
    assert validate_run_id(run_id) == run_id
    assert re.fullmatch(RUN_ID_PATTERN, run_id)


@pytest.mark.parametrize(
    "run_id",
    [
        pytest.param("", id="empty"),
        pytest.param("A" * 65, id="too long"),
        pytest.param("-run", id="leading dash"),
        pytest.param(".run", id="leading dot"),
        pytest.param("run/1", id="slash"),
        pytest.param("run 1", id="space"),
        pytest.param("run~1", id="tilde"),
        pytest.param("run@{1}", id="reflog"),
        pytest.param("run..1", id="double dot"),
        pytest.param("..", id="parent"),
        pytest.param("run.lock", id="lock suffix"),
        pytest.param("run.", id="trailing dot"),
        pytest.param("run\n1", id="newline"),
        pytest.param("run\n", id="trailing newline"),
    ],
)
def test_validate_run_id_rejects_unsafe_ids(run_id: str) -> None:
    """
    GIVEN a run id that is empty, too long, or not a safe git refname piece
    WHEN validate_run_id checks it
    THEN a ValueError names the offending id
    """
    with pytest.raises(ValueError, match="run_id"):
        validate_run_id(run_id)


def test_fresh_states_get_distinct_run_ids() -> None:
    """
    GIVEN two states built without a run_id
    WHEN their run_ids are compared
    THEN they differ
    """
    assert _state()["run_id"] != _state()["run_id"]


# ---------------------------------------------------------------------------
# Reducer channels
# ---------------------------------------------------------------------------


def test_reducer_channels_are_exactly_reducer_keys() -> None:
    """
    GIVEN the EngineState annotations with extras
    WHEN keys carrying an operator.add reducer are collected
    THEN they equal REDUCER_KEYS and nothing else carries a reducer
    """
    hints = get_type_hints(EngineState, include_extras=True)
    reducer_keys = {
        key
        for key, hint in hints.items()
        if operator.add in getattr(hint, "__metadata__", ())
    }

    assert reducer_keys == REDUCER_KEYS
    assert REDUCER_KEYS == frozenset({"trials", "verdicts", "lessons", "events"})
    assert isinstance(REDUCER_KEYS, frozenset)


def test_reducer_channels_append_deltas_under_langgraph() -> None:
    """
    GIVEN a graph over EngineState whose two nodes each return one new event
    WHEN the graph runs from initial_state
    THEN both events are appended in order while plain keys are replaced
    """
    state = _state()

    # LangGraph's node protocol names the parameter ``state``; mypy only
    # accepts functions that keep that name, so no Callable-returning factory.
    def advance(state: EngineState, phase: RunPhase) -> dict[str, object]:
        event = EngineEvent(
            run_id=state["run_id"], phase=phase, message=f"entered {phase}"
        )
        return {"events": [event], "phase": phase, "round": state["round"] + 1}

    def first(state: EngineState) -> dict[str, object]:
        return advance(state, RunPhase.understand)

    def second(state: EngineState) -> dict[str, object]:
        return advance(state, RunPhase.define)

    graph = StateGraph(EngineState)
    graph.add_node("first", first)
    graph.add_node("second", second)
    graph.add_edge(START, "first")
    graph.add_edge("first", "second")
    graph.add_edge("second", END)

    result = graph.compile().invoke(state)

    assert [event.phase for event in result["events"]] == [
        RunPhase.understand,
        RunPhase.define,
    ]
    assert result["phase"] is RunPhase.define
    assert result["round"] == 2
    assert result["trials"] == []


# ---------------------------------------------------------------------------
# Transitional alias
# ---------------------------------------------------------------------------


def test_agent_state_is_an_alias_of_engine_state() -> None:
    """
    GIVEN the transitional AgentState name
    WHEN compared with EngineState
    THEN it is the very same class
    """
    assert AgentState is EngineState
