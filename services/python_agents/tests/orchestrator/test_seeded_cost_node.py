"""D64's own cost line, the node's side: a seeded second generator call's
whole spend goes on its own counters (``seeded_calls``, ``seeded_cost_usd``),
an engine event (``seeded_call_cost``) and one run-conditions line in the
report; every other call changes nothing.

Swap point: ``_Spender`` stands for ``IdeaPipelineGenerator``. It records its
spend on the real narrowed ``Budget`` it is handed (``check``, then
``record``), then returns its result, which carries the pipeline's
``seeded_second_call`` event when the call is a seeded one, or raises its
error, which carries the pipeline's D64 note when it was raised inside a
seeded call (the pipeline's own tests prove it marks both).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any, cast

import pytest

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.common.errors import (
    BudgetExceeded,
    LLMConfigError,
    LLMUnavailable,
)
from autonomous_ai_agents.common.models import (
    ChangeClass,
    EngineEvent,
    EventLevel,
    Guardrail,
    Hypothesis,
    HypothesisSource,
    Objective,
    Project,
    Workload,
)
from autonomous_ai_agents.optimization.idea_types import GenerateEvent
from autonomous_ai_agents.optimization.sources import GenerateResult
from autonomous_ai_agents.orchestrator import nodes as nd
from autonomous_ai_agents.orchestrator.nodes import NodeContext, progress_of
from autonomous_ai_agents.orchestrator.serde import dump_state, load_state
from autonomous_ai_agents.orchestrator.state import EngineState, initial_state

ContextFactory = Callable[..., NodeContext]
SEEDED_CODE = "seeded_second_call"  # the pipeline's event code (D64)
SEEDED_NOTE = "D64: raised inside a seeded second generator call"
COST_CODE = "seeded_call_cost"
NEW_KEYS = ("seeded_calls", "seeded_cost_usd")
SEEDED = GenerateEvent(
    code=SEEDED_CODE,
    message="seeded second generator call (D64): 3 seed(s), lanes far, leap",
    data={"seeds": 3, "lanes": "far,leap"},
)
DROPPED = GenerateEvent(
    code="idea_dropped",
    message="dropped 'Use a set': its quote is not in the file",
    data={"lane": "far", "reason": "ungrounded", "title": "Use a set"},
)
S1_ONLY = "second generator call: S1 only, earlier titles avoided (D48)"
GOLDEN = "e4cf9810722b719ceb454702d90f0e2ffad54a233393d0619e66f9427dda117c"
"""The seeds-off fingerprint (``_fingerprint``) computed on HEAD 906f69a,
before D64's cost line existed."""


class _Spender:
    """Checks ``estimate``, records ``spend``, then raises ``error`` (with the
    D64 note when ``marked``) or returns ``result``."""

    def __init__(
        self,
        result: GenerateResult | None = None,
        *,
        spend: float = 0.0,
        estimate: float = 0.0,
        error: Exception | None = None,
        marked: bool = False,
    ) -> None:
        self.result = GenerateResult() if result is None else result
        self.spend, self.estimate, self.error = spend, estimate, error
        self.marked = marked

    def generate(self, **kwargs: Any) -> GenerateResult:  # noqa: ANN401
        budget = kwargs["budget"]
        assert isinstance(budget, Budget)
        try:
            budget.check(self.estimate)
            budget.record(self.spend, 100 if self.spend else 0)
            if self.error is not None:
                raise self.error
        except Exception as exc:
            if self.marked:
                exc.add_note(SEEDED_NOTE)
            raise
        return self.result


@pytest.fixture
def state(
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
) -> EngineState:
    """A 10 USD run on its second generator call, 0.1 USD of discovery spent."""
    fresh = initial_state(
        sample_project,
        [sample_workload],
        [sample_objective],
        sample_guardrails,
        run_id="run-d64",
        max_rounds=3,
        max_cost_usd=10.0,
    )
    fresh["generator_calls"] = 1
    fresh["cost_usd"] = fresh["discovery_cost_usd"] = 0.1
    return fresh


def _idea(project: Project, number: int) -> Hypothesis:
    return Hypothesis(id=f"h-{number}", project_id=project.id,
                      source=HypothesisSource.novel, title=f"idea {number}",
                      rationale="r", change_class=ChangeClass.efficiency,
                      expected_gain=0.1, provability=0.5, risk=0.1)  # fmt: skip


def _turn(
    ctx: NodeContext, state: EngineState, generator: _Spender
) -> tuple[nd.NodeDelta, list[EngineEvent]]:
    found = nd._generate(ctx, state, generator, [])
    return found.delta, found.events


def _merged(
    state: EngineState, delta: nd.NodeDelta, events: Sequence[EngineEvent]
) -> EngineState:
    merged: dict[str, Any] = {**state, **delta}
    merged["events"] = [*state["events"], *events]
    return cast(EngineState, merged)


def _codes(events: Sequence[EngineEvent]) -> list[object]:
    return [event.data.get("code") for event in events]


_VOLATILE = re.compile(r"at|created_at|id|[a-z_]+_id")


def _scrub(value: object) -> object:
    """JSON values without clocks and fixture ids (fresh on every run)."""
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if not _VOLATILE.fullmatch(k)}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def _fingerprint(
    state: EngineState, turns: Sequence[_Spender], ctx: NodeContext
) -> str:
    """Each turn's delta and events, then the final state (D64's keys left
    out) and its report, hashed."""
    record: list[object] = []
    for generator in turns:
        delta, events = _turn(ctx, state, generator)
        record.append(sorted(delta))
        state = _merged(state, delta, events)
        record.append([e.model_dump(mode="json") for e in events])
    dumped = dump_state(state)
    for key in NEW_KEYS:
        dumped.pop(key, None)
    record.append(dumped)
    now = min(e.at for e in state["events"])
    record.append(nd._report(state, "engine/", now=now))
    text = json.dumps(_scrub(record), sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()


def _seeds_off_turns(project: Project) -> list[_Spender]:
    first = GenerateResult(hypotheses=(_idea(project, 1), _idea(project, 2)),
                           notes=("a note",), events=(DROPPED,))  # fmt: skip
    second = GenerateResult(hypotheses=(_idea(project, 3),), notes=(S1_ONLY,))
    return [_Spender(first, spend=0.04), _Spender(second, spend=0.01)]


def test_seeds_off_the_state_events_and_report_are_heads(
    make_context: ContextFactory, state: EngineState, sample_project: Project
) -> None:
    """
    GIVEN a first call with an event and a note, then an S1-only second call
    THEN every delta, event, the final state (D64's keys aside) and the
         report hash to what they did on HEAD, and D64's keys stay zero
    """
    state["generator_calls"] = 0
    ctx = make_context()
    turns = _seeds_off_turns(sample_project)
    assert _fingerprint(state, turns, ctx) == GOLDEN
    for generator in turns:
        delta, events = _turn(ctx, state, generator)
        assert not set(NEW_KEYS) & set(delta) and COST_CODE not in _codes(events)
    assert (state["seeded_calls"], state["seeded_cost_usd"]) == (0, 0.0)


def test_a_seeded_second_call_adds_exactly_its_spend(
    make_context: ContextFactory, state: EngineState, sample_project: Project
) -> None:
    """
    GIVEN one earlier seeded call of 0.05 USD and a seeded call billed 0.03
    THEN the counters gain one call and exactly what ``discovery_cost_usd``
         gained, and one info ``seeded_call_cost`` event carries the call's
         USD and the run's seeded totals, after the pipeline's own event
    """
    state["seeded_calls"], state["seeded_cost_usd"] = 1, 0.05
    result = GenerateResult(hypotheses=(_idea(sample_project, 1),),
                            events=(SEEDED,))  # fmt: skip
    delta, events = _turn(make_context(), state, _Spender(result, spend=0.03))

    spent = cast(float, delta["discovery_cost_usd"]) - state["discovery_cost_usd"]
    assert spent == pytest.approx(0.03)
    assert delta["seeded_calls"] == 2
    assert delta["seeded_cost_usd"] == pytest.approx(0.05 + spent)
    codes = _codes(events)
    assert codes.index(SEEDED_CODE) < codes.index(COST_CODE)
    (cost,) = [e for e in events if e.data.get("code") == COST_CODE]
    assert cost.level is EventLevel.info
    assert cost.data == {
        "code": COST_CODE,
        "cost_usd": pytest.approx(0.03),
        "seeded_calls": 2,
        "seeded_cost_usd": pytest.approx(0.08),
        "discovery_cost_usd": pytest.approx(0.13),
    }
    assert "0.030000 USD" in cost.message and "2 call(s)" in cost.message


@pytest.mark.parametrize(
    "events",
    [
        pytest.param((), id="first or S1-only call"),
        pytest.param((DROPPED,), id="other"),
    ],
)
def test_a_first_or_s1_only_call_adds_nothing(
    make_context: ContextFactory, state: EngineState, events: tuple[GenerateEvent, ...]
) -> None:
    result = GenerateResult(notes=(S1_ONLY,), events=events)
    delta, emitted = _turn(make_context(), state, _Spender(result, spend=0.02))
    assert not set(NEW_KEYS) & set(delta) and COST_CODE not in _codes(emitted)


@pytest.mark.parametrize(
    ("error", "code"),
    [
        pytest.param(BudgetExceeded("recorded spend over"), "discovery_unaffordable",
                     id="overrun"),
        pytest.param(LLMUnavailable("529"), "generate_failed", id="soft"),
    ],
)  # fmt: skip
def test_a_seeded_call_that_fails_is_counted_with_what_it_spent(
    make_context: ContextFactory, state: EngineState, error: Exception, code: str
) -> None:
    """
    GIVEN a seeded call billed 0.02 USD that then raises BudgetExceeded or a
          soft failure carrying the pipeline's D64 note
    THEN the call and its 0.02 USD go on the seeded counters, with the event;
         the same failure without the note adds nothing
    """
    spender = _Spender(spend=0.02, error=error, marked=True)
    delta, events = _turn(make_context(), state, spender)
    assert _codes(events)[0] == code
    assert delta["seeded_calls"] == 1
    assert delta["seeded_cost_usd"] == pytest.approx(0.02)
    assert COST_CODE in _codes(events)
    plain = _Spender(spend=0.02, error=type(error)(str(error)))
    delta, events = _turn(make_context(), state, plain)
    assert not set(NEW_KEYS) & set(delta) and COST_CODE not in _codes(events)


def test_a_seeded_call_refused_before_any_spend_is_no_call(
    make_context: ContextFactory, state: EngineState
) -> None:
    """A marked BudgetExceeded with nothing spent is not a generator call
    (``generator_calls`` unchanged), so not a seeded one either."""
    spender = _Spender(estimate=100.0, marked=True)
    delta, events = _turn(make_context(), state, spender)
    assert delta["generator_calls"] == 1
    assert not set(NEW_KEYS) & set(delta) and COST_CODE not in _codes(events)


def test_a_seeded_call_that_ends_the_run_keeps_its_seeded_spend(
    make_context: ContextFactory, state: EngineState
) -> None:
    spender = _Spender(spend=0.01, error=LLMConfigError("401"), marked=True)
    with pytest.raises(LLMConfigError) as caught:
        _turn(make_context(), state, spender)
    progress = progress_of(caught.value)
    assert progress["seeded_calls"] == 1
    assert progress["seeded_cost_usd"] == pytest.approx(0.01)
    plain = _Spender(spend=0.01, error=LLMConfigError("401"))
    with pytest.raises(LLMConfigError) as caught:
        _turn(make_context(), state, plain)
    assert "seeded_calls" not in progress_of(caught.value)


def test_the_report_names_the_seeded_calls_only_when_there_were_some(
    state: EngineState,
) -> None:
    now = datetime(2026, 11, 3, 12, 0)
    before = nd._report(state, "engine/", now=now)
    assert "Seeded second generator calls" not in before
    state["seeded_calls"], state["seeded_cost_usd"] = 2, 0.0312
    state["discovery_cost_usd"] = 0.25
    after = nd._report(state, "engine/", now=now)
    line = (
        "- Seeded second generator calls (D64): 2, 0.0312 USD of 0.2500 USD discovery"
    )
    lines = before.splitlines()
    at = lines.index(f"- Peak RSS: {nd._RSS_DEFINITION}")
    assert after.splitlines() == [*lines[:at], line, *lines[at:]]


def test_the_counters_round_trip_and_an_older_state_loads_with_zeros(
    state: EngineState,
) -> None:
    """
    GIVEN a state with seeded counters set, and stored data from before D64
          (neither key, or only one)
    THEN the counters come back equal; the old data loads with zeros; any
         other missing key is still refused
    """
    state["seeded_calls"], state["seeded_cost_usd"] = 3, 0.125
    dumped = json.loads(json.dumps(dump_state(state), allow_nan=False))
    assert load_state(dumped) == state
    older = {k: v for k, v in dumped.items() if k not in NEW_KEYS}
    loaded = load_state(older)
    assert (loaded["seeded_calls"], loaded["seeded_cost_usd"]) == (0, 0.0)
    assert isinstance(loaded["seeded_cost_usd"], float)
    half = {k: v for k, v in dumped.items() if k != "seeded_cost_usd"}
    assert load_state(half)["seeded_calls"] == 3
    with pytest.raises(ValueError, match=r"missing \['generator_calls'\]"):
        load_state({k: v for k, v in older.items() if k != "generator_calls"})


def test_a_checkpoint_without_the_counters_is_read_as_zeros(
    make_context: ContextFactory, state: EngineState
) -> None:
    """A LangGraph checkpoint written before D64 has no channel for the new
    keys: a seeded call counts from zero and the report has no line."""
    old = cast(EngineState, {k: v for k, v in state.items() if k not in NEW_KEYS})
    result = GenerateResult(events=(SEEDED,))
    delta, _events = _turn(make_context(), old, _Spender(result, spend=0.02))
    assert delta["seeded_calls"] == 1
    assert delta["seeded_cost_usd"] == pytest.approx(0.02)
    report = nd._report(old, "engine/", now=datetime(2026, 11, 3, 12, 0))
    assert "Seeded second generator calls" not in report
    dumped = dump_state(old)
    assert (dumped["seeded_calls"], dumped["seeded_cost_usd"]) == (0, 0.0)


def test_a_state_from_before_d64_is_saved_with_zeros(state: EngineState) -> None:
    """
    GIVEN a run paused before D64 and resumed after it: its final state has
          neither counter, or only one
    THEN dump_state saves it with the missing counters at zero (a present one
         kept); any other missing key is still refused
    """
    state["seeded_calls"], state["seeded_cost_usd"] = 2, 0.5
    older = cast(EngineState, {k: v for k, v in state.items() if k not in NEW_KEYS})
    dumped = dump_state(older)
    assert (dumped["seeded_calls"], dumped["seeded_cost_usd"]) == (0, 0.0)
    assert isinstance(dumped["seeded_cost_usd"], float)
    assert load_state(dumped) == {**older, "seeded_calls": 0, "seeded_cost_usd": 0.0}
    half = cast(EngineState, {k: v for k, v in state.items() if k != "seeded_calls"})
    assert dump_state(half)["seeded_cost_usd"] == 0.5
    assert dump_state(half)["seeded_calls"] == 0
    with pytest.raises(ValueError, match=r"missing \['generator_calls'\]"):
        dump_state(
            cast(
                EngineState,
                {k: v for k, v in older.items() if k != "generator_calls"},
            )
        )
