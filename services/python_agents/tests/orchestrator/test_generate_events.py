"""``_generate`` hands the generator the run's facts and emits its events
(Step 3 Wave 2, N4b; amendment D44, D65).

The hypotheses node passes ``state["base_commit"]``, ``state["run_id"]``,
``state["generator_calls"]`` (as ``call_index``), the run's protected set
(the context's patterns plus ``extra_protected``) and the quality check's
frozen paths (``read_deny``) to ``HypothesisGenerator.generate``, and emits
each ``GenerateEvent`` of the result with its own code, level and data after
the ``generated`` event, before the ``generate_note`` events.

Swap point: ``_Generator`` stands for ``IdeaPipelineGenerator`` (N4a); it
records every call's keywords and returns the scripted result.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import pytest

from autonomous_ai_agents.common.models import (
    BuiltinMeasure,
    EngineEvent,
    EventLevel,
    Guardrail,
    Objective,
    Project,
    QualityCheck,
    Workload,
)
from autonomous_ai_agents.optimization.anticheat import DEFAULT_PROTECTED_PATTERNS
from autonomous_ai_agents.optimization.idea_types import GenerateEvent
from autonomous_ai_agents.optimization.sources import GenerateResult
from autonomous_ai_agents.orchestrator.nodes import NodeContext, make_nodes
from autonomous_ai_agents.orchestrator.state import EngineState, initial_state

ContextFactory = Callable[..., NodeContext]
SHA = "0123456789abcdef0123456789abcdef01234567"
QUALITY = QualityCheck(
    name="acc", measure=BuiltinMeasure.accuracy, labels="data/labels.txt",
    frozen_paths=("data/labels.txt", "data/gold.txt"),
)  # fmt: skip
EVENTS = (
    GenerateEvent(
        code="discovery_unaffordable",
        message="no lane request: the 7 lanes may cost 1.5 USD",
        level=EventLevel.warning,
        data={"stage": "lanes", "estimate_usd": 1.5},
    ),
    GenerateEvent(
        code="idea_dropped",
        message="dropped 'Use a set': its quote is not in the file",
        data={"lane": "far", "reason": "ungrounded", "title": "Use a set"},
    ),
)


class _Generator:
    """Records each call's keywords and returns ``result``."""

    def __init__(self, result: GenerateResult) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def generate(self, **kwargs: Any) -> GenerateResult:
        self.calls.append(kwargs)
        return self.result


@pytest.fixture
def state(
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
) -> EngineState:
    fresh = initial_state(
        sample_project,
        [sample_workload],
        [sample_objective],
        sample_guardrails,
        run_id="run-n4b-events",
        max_rounds=3,
        max_cost_usd=10.0,
    )
    fresh["base_commit"] = SHA
    fresh["extra_protected"] = ["bench/run.py", "data/labels.txt"]
    return fresh


def _events(delta: dict[str, object]) -> list[EngineEvent]:
    return cast(list[EngineEvent], delta["events"])


@pytest.mark.parametrize("quality", [None, QUALITY], ids=["no quality", "quality"])
def test_generate_passes_the_runs_facts(
    make_context: ContextFactory, state: EngineState, quality: QualityCheck | None
) -> None:
    """
    GIVEN a pinned base commit, a run id, one earlier generator call, the
          preflight's extra protected files and (or not) a quality check
    WHEN hypotheses calls the generator
    THEN it receives the commit, the run id, ``call_index=1``, the context's
         patterns followed by ``extra_protected``, and the frozen paths as
         ``read_deny`` (none without a quality check)
    """
    state["generator_calls"] = 1
    generator = _Generator(GenerateResult())
    ctx = make_context(generator=generator, quality=quality)

    make_nodes(ctx)["hypotheses"](state)

    (call,) = generator.calls
    assert call["commit"] == SHA and call["run_id"] == "run-n4b-events"
    assert call["call_index"] == 1
    assert tuple(call["protected"]) == (
        *DEFAULT_PROTECTED_PATTERNS,
        "bench/run.py",
        "data/labels.txt",
    )
    expected = () if quality is None else ("data/labels.txt", "data/gold.txt")
    assert tuple(call["read_deny"]) == expected


def test_a_first_call_has_index_zero_and_a_missing_commit_is_passed_as_none(
    make_context: ContextFactory, state: EngineState
) -> None:
    """No base commit (a stub context) reaches the generator as ``None``, which
    sends the pipeline down its no-code path (D48)."""
    state["base_commit"] = None
    generator = _Generator(GenerateResult())
    make_nodes(make_context(generator=generator))["hypotheses"](state)
    (call,) = generator.calls
    assert call["commit"] is None and call["call_index"] == 0


def test_generate_emits_each_event_with_its_code_level_and_data(
    make_context: ContextFactory, state: EngineState
) -> None:
    """
    GIVEN a result with two events and a note
    WHEN hypotheses runs
    THEN ``generated`` comes first, then each event with its own code, level
         and data (``code`` from the event), then the ``generate_note``
    """
    generator = _Generator(GenerateResult(notes=("one note",), events=EVENTS))
    delta = make_nodes(make_context(generator=generator))["hypotheses"](state)

    events = _events(dict(delta))
    codes = [event.data.get("code") for event in events]
    start = codes.index("generated")
    assert codes[start:-1] == [  # the last is the round's own announcement
        "generated",
        "discovery_unaffordable",
        "idea_dropped",
        "generate_note",
    ]
    unaffordable, dropped = events[start + 1], events[start + 2]
    assert unaffordable.level is EventLevel.warning
    assert unaffordable.message == (
        "discovery_unaffordable: no lane request: the 7 lanes may cost 1.5 USD"
    )
    assert unaffordable.data == {
        "code": "discovery_unaffordable",
        "stage": "lanes",
        "estimate_usd": 1.5,
    }
    assert dropped.level is EventLevel.info
    assert dropped.data == {
        "code": "idea_dropped",
        "lane": "far",
        "reason": "ungrounded",
        "title": "Use a set",
    }
    assert events[start + 3].message == "generate_note: one note"


def test_a_result_without_events_emits_what_it_did_before(
    make_context: ContextFactory, state: EngineState
) -> None:
    """Today's generator returns no events: only ``generated`` and the notes."""
    generator = _Generator(GenerateResult(notes=("a", "b")))
    delta = make_nodes(make_context(generator=generator))["hypotheses"](state)
    codes = [event.data.get("code") for event in _events(dict(delta))]
    start = codes.index("generated")
    assert codes[start:] == ["generated", "generate_note", "generate_note", None]
