"""Tests for the engine loop nodes (Step 1, unit U7).

Every node is a closure over a ``NodeContext`` (``make_nodes``) that takes
the state and returns only its delta: the keys it changes, plus one event,
and for the append-only channels (``REDUCER_KEYS``) only the new items. The
tests below drive the nodes through a tiny merger that mimics LangGraph's
reducers, so no graph is involved except for ``approval_gate``, whose
``interrupt()`` needs a running graph.
"""

from __future__ import annotations

import math
import os
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any, TypeVar, cast

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.common.config import IsolationMode, settings
from autonomous_ai_agents.common.errors import (
    BudgetExceeded,
    LLMConfigError,
    LLMRequestError,
    LLMUnavailable,
    PreflightError,
    RepoTamperedError,
    TrialUnaffordable,
    add_spend,
)
from autonomous_ai_agents.common.models import (
    METRIC_PEAK_RSS_BYTES,
    METRIC_TESTS_PASSED,
    METRIC_WALL_TIME_S,
    ApprovalDecision,
    ApprovalRequest,
    Baseline,
    ChangeClass,
    Combination,
    CombineSkip,
    Delivery,
    DeliveryKind,
    Direction,
    EngineEvent,
    EventLevel,
    Guardrail,
    GuardrailKind,
    Hotspot,
    Hypothesis,
    HypothesisSource,
    HypothesisStatus,
    JudgeOutcome,
    JudgeResult,
    Lesson,
    Measurement,
    Objective,
    ObjectiveKind,
    Project,
    ProjectUnderstanding,
    RunPhase,
    RunStats,
    Technique,
    Trial,
    TrialStatus,
    Verdict,
    VerdictOutcome,
    Violation,
    ViolationRule,
    Workload,
)
from autonomous_ai_agents.execution.fakes import (
    CombineCall,
    FakeCombiner,
    FakePreflight,
    FakeProfiler,
    FakePublisher,
    FakeUnderstander,
    PreflightCall,
    ProfileCall,
    PublishCall,
    UnderstandCall,
)
from autonomous_ai_agents.execution.protocols import (
    CombineMeasured,
    KeptChange,
    PreflightReport,
    TrialBrief,
    UnderstandResult,
)
from autonomous_ai_agents.execution.runner import (
    OVER_BUDGET_ERROR,
    ScriptedOutcome,
    StubBaselineRunner,
    StubTrialRunner,
)
from autonomous_ai_agents.optimization.anticheat import DEFAULT_PROTECTED_PATTERNS
from autonomous_ai_agents.orchestrator.main import build_checkpointer, run_config
from autonomous_ai_agents.orchestrator.nodes import (
    BRIEF_FALLBACK_HOTSPOTS,
    LOOP_NODES,
    NODE_NAMES,
    DeliveryError,
    EngineError,
    NodeContext,
    NodeDelta,
    NodeFn,
    assert_safe_branch,
    decided_verdicts,
    make_nodes,
    make_router,
    measurement_violations,
    progress_of,
    trial_ref_cleanup,
)
from autonomous_ai_agents.orchestrator.state import (
    REDUCER_KEYS,
    EngineState,
    initial_state,
)
from autonomous_ai_agents.persistence.repository import InMemoryRepository

ContextFactory = Callable[..., NodeContext]
VAL_LOSS = "val_loss"
RUN_ID = "run-0001-abcd-ef00"
T = TypeVar("T")

LINEAR_PATH: tuple[str, ...] = (
    *LOOP_NODES,
    "combine",
    "deliver",
    "learn",
    "watch",
)
"""Every node but approval_gate, in the order the graph visits them."""

PHASE_AFTER: dict[str, RunPhase] = {
    "connect": RunPhase.connect,
    "understand": RunPhase.understand,
    "define": RunPhase.define,
    "baseline": RunPhase.baseline,
    "profile": RunPhase.profile,
    "research": RunPhase.research,
    "hypotheses": RunPhase.hypotheses,
    "trials": RunPhase.trials,
    "judges": RunPhase.judges,
    "verdicts": RunPhase.verdicts,
    "combine": RunPhase.combine,
    "deliver": RunPhase.deliver,
    "learn": RunPhase.learn,
    "watch": RunPhase.done,
}

EVENT_PHASE: dict[str, RunPhase] = {**PHASE_AFTER, "watch": RunPhase.watch}

EXPECTED_KEYS: dict[str, frozenset[str]] = {
    "connect": frozenset({"phase", "events"}),
    "understand": frozenset({"phase", "events"}),
    "define": frozenset({"phase", "objectives", "events"}),
    "baseline": frozenset({"phase", "baseline", "events"}),
    "profile": frozenset({"phase", "hotspots", "events"}),
    "research": frozenset({"phase", "techniques", "papers", "events"}),
    "hypotheses": frozenset({"phase", "round", "hypotheses", "events"}),
    "trials": frozenset(
        {"phase", "round_trials", "hypotheses", "cost_usd", "tokens_used", "events"}
    ),
    "judges": frozenset({"phase", "trials", "round_trials", "events"}),
    "verdicts": frozenset(
        {"phase", "verdicts", "hypotheses", "pending_approval_ids", "events"}
    ),
    "combine": frozenset({"phase", "kept_verdict_ids", "events"}),
    "deliver": frozenset({"phase", "delivery", "events"}),
    "learn": frozenset({"phase", "lessons", "events"}),
    "watch": frozenset({"phase", "events"}),
}


# ---------------------------------------------------------------------------
# Helpers: a minimal reducer-aware merger and typed delta readers
# ---------------------------------------------------------------------------


def _apply(state: EngineState, delta: NodeDelta) -> EngineState:
    """Merge ``delta`` into ``state`` the way LangGraph's reducers would."""
    merged: dict[str, Any] = dict(state)
    for key, value in delta.items():
        if key in REDUCER_KEYS:
            assert isinstance(value, list), key
            merged[key] = [*merged[key], *value]
        else:
            merged[key] = value
    return cast(EngineState, merged)


def _advance(
    nodes: Mapping[str, NodeFn], state: EngineState, names: Sequence[str]
) -> EngineState:
    for name in names:
        state = _apply(state, nodes[name](state))
    return state


def _before(name: str) -> tuple[str, ...]:
    """Linear-path node names strictly before ``name``."""
    return LINEAR_PATH[: LINEAR_PATH.index(name)]


def _items(delta: Mapping[str, object], key: str, kind: type[T]) -> list[T]:
    value = delta[key]
    assert isinstance(value, list), key
    assert all(isinstance(item, kind) for item in value), key
    return cast(list[T], value)


def _events(delta: NodeDelta) -> list[EngineEvent]:
    return _items(delta, "events", EngineEvent)


def _only_event(delta: NodeDelta) -> EngineEvent:
    events = _events(delta)
    assert len(events) == 1
    return events[0]


def _hotspot(project: Project, workload: Workload, *tags: str) -> Hotspot:
    return Hotspot(
        project_id=project.id,
        workload_id=workload.id,
        file_path="src/bridge/encoder.py",
        symbol="encode",
        self_time_s=0.7,
        total_time_s=0.8,
        share=0.42,
        tags=tags,
    )


def _spots(project: Project, workload: Workload, *shares: float) -> list[Hotspot]:
    """One hotspot per share, in profile order, each in its own function."""
    return [
        Hotspot(
            project_id=project.id,
            workload_id=workload.id,
            file_path=f"src/bridge/m{index}.py",
            symbol=f"f{index}",
            self_time_s=share,
            total_time_s=share,
            share=share,
        )
        for index, share in enumerate(shares)
    ]


class _BriefRecordingRunner:
    """Delegates to a stub runner, recording each hypothesis and brief."""

    def __init__(self, inner: StubTrialRunner) -> None:
        self.inner = inner
        self.hypotheses: list[Hypothesis] = []
        self.briefs: list[TrialBrief] = []

    def run(
        self,
        hypothesis: Hypothesis,
        workloads: Sequence[Workload],
        baseline: Baseline,
        *,
        round: int,
        branch: str,
        budget_usd: float,
        brief: TrialBrief,
    ) -> Trial:
        self.hypotheses.append(hypothesis)
        self.briefs.append(brief)
        return self.inner.run(
            hypothesis,
            workloads,
            baseline,
            round=round,
            branch=branch,
            budget_usd=budget_usd,
            brief=brief,
        )


SEED_TRIAL = Trial(
    id="seed-trial",
    hypothesis_id="seed-hypothesis",
    round=1,
    status=TrialStatus.measured,
)
SEED_VERDICT = Verdict(
    id="seed-verdict",
    trial_id=SEED_TRIAL.id,
    hypothesis_id=SEED_TRIAL.hypothesis_id,
    outcome=VerdictOutcome.inconclusive,
    change_class=ChangeClass.efficiency,
    summary="seeded verdict from an earlier round",
)
SEED_LESSON = Lesson(
    id="seed-lesson", outcome=VerdictOutcome.inconclusive, text="seeded lesson"
)
SEED_EVENT = EngineEvent(run_id=RUN_ID, phase=RunPhase.connect, message="seeded")


def _seeded(state: EngineState) -> EngineState:
    """``state`` with one earlier item already on every reducer channel."""
    seeds: dict[str, object] = {
        "trials": SEED_TRIAL,
        "verdicts": SEED_VERDICT,
        "lessons": SEED_LESSON,
        "events": SEED_EVENT,
    }
    assert set(seeds) == REDUCER_KEYS
    merged: dict[str, Any] = dict(state)
    for key, seed in seeds.items():
        merged[key] = [*merged[key], seed]
    return cast(EngineState, merged)


def _measurement(
    workload_id: str, metric: str, samples: Sequence[float], unit: str = "s"
) -> Measurement:
    values = tuple(samples)
    return Measurement(
        workload_id=workload_id,
        metric=metric,
        stats=RunStats.from_samples(values, unit=unit),
        samples=values,
    )


class _TamperingRunner:
    """A trial runner that rewrites the stub's Trial before returning it."""

    def __init__(self, inner: StubTrialRunner, update: Mapping[str, object]) -> None:
        self._inner = inner
        self._update = dict(update)

    def run(
        self,
        hypothesis: Hypothesis,
        workloads: Sequence[Workload],
        baseline: Baseline,
        *,
        round: int,
        branch: str,
        budget_usd: float,
        brief: TrialBrief,
    ) -> Trial:
        trial = self._inner.run(
            hypothesis,
            workloads,
            baseline,
            round=round,
            branch=branch,
            budget_usd=budget_usd,
            brief=brief,
        )
        return trial.model_copy(update=self._update)


class _CherryPickingRunner:
    """Reports a fast copy of every wall-time measurement ahead of the real one."""

    def __init__(self, inner: StubTrialRunner) -> None:
        self._inner = inner

    def run(
        self,
        hypothesis: Hypothesis,
        workloads: Sequence[Workload],
        baseline: Baseline,
        *,
        round: int,
        branch: str,
        budget_usd: float,
        brief: TrialBrief,
    ) -> Trial:
        trial = self._inner.run(
            hypothesis,
            workloads,
            baseline,
            round=round,
            branch=branch,
            budget_usd=budget_usd,
            brief=brief,
        )
        fast = tuple(
            _measurement(m.workload_id, m.metric, (1.0,) * 5)
            for m in trial.measurements
            if m.metric == METRIC_WALL_TIME_S
        )
        return trial.model_copy(update={"measurements": (*fast, *trial.measurements)})


class _GuardrailDodgingRunner:
    """Reports a healthy copy of every val_loss measurement ahead of the real one."""

    def __init__(self, inner: StubTrialRunner) -> None:
        self._inner = inner

    def run(
        self,
        hypothesis: Hypothesis,
        workloads: Sequence[Workload],
        baseline: Baseline,
        *,
        round: int,
        branch: str,
        budget_usd: float,
        brief: TrialBrief,
    ) -> Trial:
        trial = self._inner.run(
            hypothesis,
            workloads,
            baseline,
            round=round,
            branch=branch,
            budget_usd=budget_usd,
            brief=brief,
        )
        healthy = tuple(
            _measurement(m.workload_id, m.metric, (0.5,) * 5, unit="")
            for m in trial.measurements
            if m.metric == VAL_LOSS
        )
        return trial.model_copy(
            update={"measurements": (*healthy, *trial.measurements)}
        )


class _DoublingBaselineRunner:
    """A baseline runner that reports every measurement twice."""

    def __init__(self, inner: StubBaselineRunner) -> None:
        self._inner = inner

    def measure(
        self, workloads: Sequence[Workload], *, run_id: str, commit: str | None
    ) -> tuple[Measurement, ...]:
        measured = self._inner.measure(workloads, run_id=run_id, commit=commit)
        return (*measured, *measured)


def _single_node_graph(
    node: NodeFn, name: str
) -> CompiledStateGraph[EngineState, None, EngineState, EngineState]:
    graph: StateGraph[EngineState, None, EngineState, EngineState] = StateGraph(
        EngineState
    )
    graph.add_node(name, node)
    graph.add_edge(START, name)
    graph.add_edge(name, END)
    return graph.compile(checkpointer=build_checkpointer())


@pytest.fixture
def base_state(
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
) -> EngineState:
    """The state a run starts from, with a fixed run id and three rounds."""
    return initial_state(
        sample_project,
        [sample_workload],
        [sample_objective],
        sample_guardrails,
        run_id=RUN_ID,
        max_rounds=3,
    )


# ---------------------------------------------------------------------------
# make_nodes, NodeContext and errors
# ---------------------------------------------------------------------------


class TestMakeNodes:
    def test_returns_every_node_in_loop_order(
        self, make_context: ContextFactory
    ) -> None:
        """
        GIVEN a node context
        WHEN make_nodes builds the node functions
        THEN the keys are exactly NODE_NAMES in graph order and all callable
        """
        nodes = make_nodes(make_context())

        assert tuple(nodes) == NODE_NAMES
        assert NODE_NAMES[: len(LOOP_NODES)] == LOOP_NODES
        assert NODE_NAMES[-5:] == (
            "approval_gate",
            "combine",
            "deliver",
            "learn",
            "watch",
        )
        assert all(callable(node) for node in nodes.values())

    def test_context_is_frozen_with_settings_defaults(
        self, make_context: ContextFactory
    ) -> None:
        """
        GIVEN a node context built with defaults
        WHEN its knobs are read and one is assigned
        THEN the knobs mirror settings and the assignment is refused
        """
        ctx = make_context()

        assert ctx.protected_patterns == DEFAULT_PROTECTED_PATTERNS
        assert ctx.min_runs == settings.MIN_RUNS
        assert not hasattr(ctx, "noise_multiplier")  # the judges own the noise rule
        assert ctx.branch_prefix == settings.TRIAL_BRANCH_PREFIX
        assert ctx.max_hypotheses_per_round == 3
        assert ctx.candidates == () and ctx.hotspots == () and ctx.techniques == ()
        with pytest.raises(FrozenInstanceError):
            ctx.min_runs = 1  # type: ignore[misc]

    def test_duplicate_candidate_ids_are_refused(
        self, make_context: ContextFactory, h1_cache: Hypothesis
    ) -> None:
        """
        GIVEN two candidates sharing one id
        WHEN a node context is built over them
        THEN a ValueError names the repeated id (each would be trialled twice)
        """
        with pytest.raises(ValueError, match=h1_cache.id):
            make_context([h1_cache, h1_cache.model_copy(update={"title": "again"})])

    @pytest.mark.parametrize("bad_id", ["", "../main", "a b", "x.lock", "-x"])
    def test_candidate_ids_must_be_refname_safe(
        self, make_context: ContextFactory, h1_cache: Hypothesis, bad_id: str
    ) -> None:
        """
        GIVEN a candidate whose id cannot be part of a git branch name
        WHEN a node context is built over it
        THEN a ValueError names the candidate id
        """
        with pytest.raises(ValueError, match="candidate id"):
            make_context([h1_cache.model_copy(update={"id": bad_id})])

    @pytest.mark.parametrize(
        ("field", "value"),
        [("max_hypotheses_per_round", 0), ("min_runs", 0), ("min_runs", -1)],
    )
    def test_rigour_knobs_must_be_at_least_one(
        self, make_context: ContextFactory, field: str, value: int
    ) -> None:
        """
        GIVEN max_hypotheses_per_round or min_runs below 1
        WHEN a node context is built
        THEN a ValueError names the knob
        """
        with pytest.raises(ValueError, match=field):
            make_context(**{field: value})

    def test_delivery_error_is_an_engine_error(self) -> None:
        """
        GIVEN the node error types
        WHEN their hierarchy is inspected
        THEN DeliveryError is an EngineError, which is an Exception
        """
        assert issubclass(DeliveryError, EngineError)
        assert issubclass(EngineError, Exception)


# ---------------------------------------------------------------------------
# Contract shared by every node on the linear path
# ---------------------------------------------------------------------------


class TestNodeContract:
    @pytest.fixture
    def nodes(
        self,
        make_context: ContextFactory,
        h1_cache: Hypothesis,
        h2_protected: Hypothesis,
        h3_noise: Hypothesis,
        h4_behaviour: Hypothesis,
    ) -> dict[str, NodeFn]:
        ctx = make_context(
            [h1_cache, h2_protected, h3_noise, h4_behaviour],
            max_hypotheses_per_round=4,
        )
        return make_nodes(ctx)

    @pytest.mark.parametrize("name", LINEAR_PATH)
    def test_node_returns_only_its_delta_keys_and_sets_phase(
        self, name: str, nodes: dict[str, NodeFn], base_state: EngineState
    ) -> None:
        """
        GIVEN the state just before a node on the linear path
        WHEN the node runs
        THEN its delta holds exactly the documented keys and the node's phase
        """
        state = _advance(nodes, base_state, _before(name))

        delta = nodes[name](state)

        assert set(delta) == EXPECTED_KEYS[name]
        assert delta["phase"] is PHASE_AFTER[name]

    @pytest.mark.parametrize("name", LINEAR_PATH)
    def test_node_emits_events_for_its_phase(
        self, name: str, nodes: dict[str, NodeFn], base_state: EngineState
    ) -> None:
        """
        GIVEN the state just before a node on the linear path
        WHEN the node runs
        THEN every event in its delta carries the run id and the node's phase
        """
        state = _advance(nodes, base_state, _before(name))

        events = _events(nodes[name](state))

        assert events
        assert all(event.run_id == RUN_ID for event in events)
        assert all(event.phase is EVENT_PHASE[name] for event in events)

    @pytest.mark.parametrize("name", LINEAR_PATH)
    def test_reducer_deltas_hold_only_new_items(
        self, name: str, nodes: dict[str, NodeFn], base_state: EngineState
    ) -> None:
        """
        GIVEN a state seeded with one earlier trial, verdict, lesson and event
              on top of whatever the run produced so far
        WHEN a node runs
        THEN no reducer delta repeats a seeded or an existing item
        """
        state = _seeded(_advance(nodes, base_state, _before(name)))
        channels: dict[str, Any] = dict(state)
        before = {key: list(channels[key]) for key in REDUCER_KEYS}
        seeds = (SEED_TRIAL, SEED_VERDICT, SEED_LESSON, SEED_EVENT)

        delta = nodes[name](state)

        assert delta["events"]
        for key in REDUCER_KEYS & set(delta):
            new_items = delta[key]
            assert isinstance(new_items, list)
            assert not any(item in before[key] for item in new_items), key
            assert not any(item in seeds for item in new_items), key


# ---------------------------------------------------------------------------
# connect, understand, define
# ---------------------------------------------------------------------------


class TestConnect:
    def test_announces_project_and_workload_count(
        self, make_context: ContextFactory, base_state: EngineState
    ) -> None:
        """
        GIVEN a state with one workload
        WHEN connect runs
        THEN the event names the project and counts the workloads
        """
        delta = make_nodes(make_context())["connect"](base_state)

        event = _only_event(delta)
        assert event.message == "connected bridge"
        assert event.data == {"workloads": 1}


class TestUnderstand:
    def test_is_a_stub_without_llm_calls(
        self, make_context: ContextFactory, base_state: EngineState
    ) -> None:
        """
        GIVEN any state
        WHEN understand runs
        THEN it only reports itself as a stub
        """
        delta = make_nodes(make_context())["understand"](base_state)

        assert "stub" in _only_event(delta).message


class TestDefine:
    def test_keeps_given_objectives_and_lists_them(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_objective: Objective,
    ) -> None:
        """
        GIVEN a state whose objectives are set
        WHEN define runs
        THEN the objectives are kept and the event lists metrics and guardrails
        """
        delta = make_nodes(make_context())["define"](base_state)

        assert _items(delta, "objectives", Objective) == [sample_objective]
        event = _only_event(delta)
        assert event.data == {
            "objectives": METRIC_WALL_TIME_S,
            "guardrails": "tests_pass, metric_bound",
            "min_runs": settings.MIN_RUNS,
        }

    def test_defaults_to_minimizing_wall_time(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        GIVEN a state with no objectives and MIN_RELATIVE_GAIN set to 5 %
        WHEN define runs
        THEN one runtime objective minimizing wall time is created for the
             project, with the configured minimum relative gain
        """
        monkeypatch.setattr(settings, "MIN_RELATIVE_GAIN", 0.05)
        base_state["objectives"] = []

        delta = make_nodes(make_context())["define"](base_state)

        (objective,) = _items(delta, "objectives", Objective)
        assert objective.kind is ObjectiveKind.runtime
        assert objective.metric == METRIC_WALL_TIME_S
        assert objective.direction is Direction.minimize
        assert objective.min_relative_gain == 0.05
        assert objective.project_id == base_state["project"].id
        assert objective.description == "minimize wall time"


class TestDefaultMemoryBound:
    def test_the_default_objective_also_bounds_peak_memory(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_guardrails: tuple[Guardrail, ...],
    ) -> None:
        """
        GIVEN no objectives (the default "faster and leaner") and guardrails
              without a peak RSS bound
        WHEN define runs
        THEN the user's guardrails are kept and one more bounds peak RSS: a
             trial may not grow it by more than 10 %
        """
        base_state["objectives"] = []

        delta = make_nodes(make_context())["define"](base_state)

        *kept, bound = _items(delta, "guardrails", Guardrail)
        assert kept == list(sample_guardrails)
        assert bound.kind is GuardrailKind.metric_bound
        assert bound.metric == METRIC_PEAK_RSS_BYTES
        assert bound.direction is Direction.minimize
        assert bound.max_drop == pytest.approx(0.10)
        assert bound.project_id == base_state["project"].id
        assert "metric_bound" in str(_only_event(delta).data["guardrails"])

    def test_a_peak_rss_bound_of_the_users_own_is_left_alone(
        self, make_context: ContextFactory, base_state: EngineState
    ) -> None:
        own = Guardrail(
            project_id=base_state["project"].id,
            kind=GuardrailKind.metric_bound,
            metric=METRIC_PEAK_RSS_BYTES,
            max_drop=0.5,
            direction=Direction.minimize,
            description="memory may grow by half",
        )
        base_state["objectives"], base_state["guardrails"] = [], [own]

        delta = make_nodes(make_context())["define"](base_state)

        assert "guardrails" not in delta

    def test_a_default_run_rejects_a_trial_that_grows_memory(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN the default objective, and H1 3x faster but with 27x the peak RSS
        WHEN the run goes through verdicts
        THEN H1 is rejected by the guardrail judge naming peak RSS
        """
        fat = ScriptedOutcome(
            samples={
                METRIC_WALL_TIME_S: (0.6,) * 5,
                METRIC_PEAK_RSS_BYTES: (27e7,) * 5,
            },
            touched_paths=("src/bridge/encoder.py",),
        )
        base = ScriptedOutcome(
            samples={
                METRIC_WALL_TIME_S: (1.8,) * 5,
                METRIC_PEAK_RSS_BYTES: (1e7,) * 5,
            }
        )
        base_state["objectives"], base_state["guardrails"] = [], []
        nodes = make_nodes(
            make_context(
                [h1_cache],
                scripts={h1_cache.title: fat},
                baseline_runner=StubBaselineRunner(base),
            )
        )

        state = _advance(nodes, base_state, _before("combine"))

        (verdict,) = state["verdicts"]
        assert verdict.outcome is VerdictOutcome.reject
        assert METRIC_PEAK_RSS_BYTES in verdict.summary


# ---------------------------------------------------------------------------
# baseline
# ---------------------------------------------------------------------------


class TestBaseline:
    def test_measures_workloads_into_a_baseline(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_objective: Objective,
        sample_guardrails: tuple[Guardrail, ...],
    ) -> None:
        """
        GIVEN a scripted baseline runner
        WHEN baseline runs
        THEN the baseline carries measurements, objectives and guardrails,
             the event reports n and the primary metric's mean, and the
             workload's noisy_host note (Step 2) follows it
        """
        delta = make_nodes(make_context())["baseline"](base_state)

        baseline = delta["baseline"]
        assert isinstance(baseline, Baseline)
        assert baseline.objectives == (sample_objective,)
        assert baseline.guardrails == sample_guardrails
        assert {m.metric for m in baseline.measurements} == {
            METRIC_WALL_TIME_S,
            VAL_LOSS,
            "tests_passed",
        }
        assert all(m.trial_id is None for m in baseline.measurements)
        event, note = _events(delta)
        assert note.data["code"] == "noisy_host"
        assert event.data["metric"] == METRIC_WALL_TIME_S
        assert event.data["n"] == 5
        assert event.data["mean"] == pytest.approx(1.80)

    def test_passes_the_run_id_and_base_commit_to_the_runner(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        baseline_script: ScriptedOutcome,
        sample_workload: Workload,
    ) -> None:
        """
        GIVEN a state whose connect pinned base commit abc123
        WHEN baseline runs
        THEN the runner is asked to measure the workloads for this run id
             at that commit (its worktree is <run>/baseline at the base)
        """
        runner = StubBaselineRunner(baseline_script)
        state = cast(EngineState, {**base_state, "base_commit": "abc123"})

        make_nodes(make_context(baseline_runner=runner))["baseline"](state)

        assert runner.calls == [((sample_workload.id,), RUN_ID, "abc123")]

    def test_passes_no_commit_while_connect_pins_none(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        baseline_script: ScriptedOutcome,
    ) -> None:
        """
        GIVEN a fresh state (the Step 1 connect stub pins no commit)
        WHEN baseline runs
        THEN the runner gets commit None and the run id
        """
        runner = StubBaselineRunner(baseline_script)

        make_nodes(make_context(baseline_runner=runner))["baseline"](base_state)

        assert [(run_id, commit) for _, run_id, commit in runner.calls] == [
            (RUN_ID, None)
        ]

    def test_raises_when_an_objective_metric_has_too_few_runs(
        self, make_context: ContextFactory, base_state: EngineState
    ) -> None:
        """
        GIVEN a baseline runner reporting three wall-time runs
        WHEN baseline runs with min_runs 5
        THEN an EngineError says the baseline is untrustworthy
        """
        script = ScriptedOutcome(samples={METRIC_WALL_TIME_S: (1.8, 1.8, 1.8)})
        ctx = make_context(baseline_runner=StubBaselineRunner(script))

        with pytest.raises(EngineError, match="3 runs measured; at least 5"):
            make_nodes(ctx)["baseline"](base_state)

    def test_run_count_rule_exempts_guardrail_and_test_metrics(
        self, make_context: ContextFactory, base_state: EngineState
    ) -> None:
        """
        GIVEN a baseline with two val_loss runs and a single tests_passed run
        WHEN baseline runs
        THEN no error is raised because only objective metrics need min_runs
        """
        script = ScriptedOutcome(
            samples={METRIC_WALL_TIME_S: (1.8,) * 5, VAL_LOSS: (0.5, 0.5)},
            tests_passed=True,
        )
        ctx = make_context(baseline_runner=StubBaselineRunner(script))

        delta = make_nodes(ctx)["baseline"](base_state)

        assert isinstance(delta["baseline"], Baseline)

    def test_raises_when_an_objective_metric_is_not_measured(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_workload: Workload,
    ) -> None:
        """
        GIVEN a baseline runner that measures nothing
        WHEN baseline runs
        THEN an EngineError lists the missing (workload, metric) measurement
        """
        ctx = make_context(baseline_runner=StubBaselineRunner(ScriptedOutcome()))

        with pytest.raises(EngineError) as raised:
            make_nodes(ctx)["baseline"](base_state)

        assert str(raised.value) == (
            "baseline is not trustworthy: missing_measurement: metric "
            f"{METRIC_WALL_TIME_S} was not measured on workload {sample_workload.id}; "
            f"missing_measurement: metric {VAL_LOSS} was not measured on workload "
            f"{sample_workload.id}"
        )

    def test_raises_when_a_guardrail_metric_is_not_measured(
        self, make_context: ContextFactory, base_state: EngineState
    ) -> None:
        """
        GIVEN a baseline runner that never measures val_loss while a guardrail
              bounds it
        WHEN the baseline node runs
        THEN it raises EngineError naming the missing guardrail metric: a bound
             against nothing is no bound
        """
        no_val_loss = ScriptedOutcome(
            samples={METRIC_WALL_TIME_S: (1.8,) * 5}, tests_passed=True
        )
        nodes = make_nodes(
            make_context(baseline_runner=StubBaselineRunner(no_val_loss))
        )
        state = _advance(nodes, base_state, _before("baseline"))

        with pytest.raises(EngineError, match=f"missing_measurement.*{VAL_LOSS}"):
            nodes["baseline"](state)

    def test_raises_when_a_workload_reports_an_objective_metric_twice(
        self, make_context: ContextFactory, base_state: EngineState
    ) -> None:
        """
        GIVEN a baseline runner that reports every measurement twice
        WHEN baseline runs
        THEN an EngineError names the duplicate measurement
        """
        ctx = make_context(
            baseline_runner=_DoublingBaselineRunner(
                StubBaselineRunner(
                    ScriptedOutcome(samples={METRIC_WALL_TIME_S: (1.8,) * 5})
                )
            )
        )

        with pytest.raises(EngineError, match="duplicate_measurement: .* 2 times"):
            make_nodes(ctx)["baseline"](base_state)

    def test_without_objectives_the_event_reports_no_measurement(
        self, make_context: ContextFactory, base_state: EngineState
    ) -> None:
        """
        GIVEN a state with no objectives (define has not run) and nothing measured
        WHEN baseline runs
        THEN nothing is required, the baseline is empty and the event says so
        """
        base_state["objectives"] = []
        base_state["guardrails"] = []
        ctx = make_context(baseline_runner=StubBaselineRunner(ScriptedOutcome()))

        delta = make_nodes(ctx)["baseline"](base_state)

        event = _only_event(delta)
        assert event.data["n"] == 0
        assert event.data["mean"] is None
        assert "no measurement" in event.message


# ---------------------------------------------------------------------------
# measurement_violations
# ---------------------------------------------------------------------------


class TestMeasurementViolations:
    METRICS = (METRIC_WALL_TIME_S, METRIC_PEAK_RSS_BYTES)

    def _complete(self, *workload_ids: str) -> list[Measurement]:
        return [
            _measurement(workload_id, metric, (1.0,) * 5)
            for workload_id in workload_ids
            for metric in self.METRICS
        ]

    def test_one_measurement_per_workload_and_objective_metric_passes(self) -> None:
        """
        GIVEN exactly one five-run measurement per (workload, objective metric)
        WHEN measurement_violations checks them
        THEN there is no violation
        """
        assert (
            measurement_violations(
                self._complete("w1", "w2"), ("w1", "w2"), self.METRICS, 5
            )
            == ()
        )

    def test_guardrail_metrics_must_be_measured_exactly_once_too(self) -> None:
        """
        GIVEN a guardrail metric that is missing on w1, doubled on w2 and
              measured from a single run on w3
        WHEN measurement_violations checks them with the guardrail metric
        THEN w1 is missing, w2 is a duplicate and w3 is fine (guardrails are
             bounded, not proven, so they need no minimum run count)
        """
        rows = [
            *self._complete("w1", "w2", "w3"),
            _measurement("w2", "val_loss", (0.5,) * 5),
            _measurement("w2", "val_loss", (0.9,) * 5),
            _measurement("w3", "val_loss", (0.5,)),
        ]

        violations = measurement_violations(
            rows, ("w1", "w2", "w3"), self.METRICS, 5, guardrail_metrics=("val_loss",)
        )

        assert [v.rule for v in violations] == [
            ViolationRule.missing_measurement,
            ViolationRule.duplicate_measurement,
        ]
        assert "val_loss" in violations[0].message and "w1" in violations[0].message
        assert "val_loss" in violations[1].message and "w2" in violations[1].message

    def test_a_missing_pair_is_reported_per_workload_and_metric(self) -> None:
        """
        GIVEN peak memory measured on w1 but not on w2
        WHEN measurement_violations checks them
        THEN one missing_measurement names the metric and w2
        """
        rows = [
            m
            for m in self._complete("w1", "w2")
            if not (m.workload_id == "w2" and m.metric == METRIC_PEAK_RSS_BYTES)
        ]

        (violation,) = measurement_violations(rows, ("w1", "w2"), self.METRICS, 5)

        assert violation.rule is ViolationRule.missing_measurement
        assert violation.message == (
            f"metric {METRIC_PEAK_RSS_BYTES} was not measured on workload w2"
        )

    def test_a_duplicate_pair_is_reported(self) -> None:
        """
        GIVEN wall time reported twice for w1 (a fast copy first)
        WHEN measurement_violations checks them
        THEN one duplicate_measurement names the metric, the workload and the count
        """
        rows = [
            _measurement("w1", METRIC_WALL_TIME_S, (0.1,) * 5),
            *self._complete("w1"),
        ]

        (violation,) = measurement_violations(rows, ("w1",), self.METRICS, 5)

        assert violation.rule is ViolationRule.duplicate_measurement
        assert f"metric {METRIC_WALL_TIME_S} was measured 2 times on workload w1" in (
            violation.message
        )

    def test_a_single_measurement_with_too_few_runs_is_reported(self) -> None:
        """
        GIVEN one wall-time measurement over three runs
        WHEN measurement_violations checks it with min_runs 5
        THEN one too_few_runs violation names the metric and workload
        """
        rows = [
            _measurement("w1", METRIC_WALL_TIME_S, (1.0,) * 3),
            _measurement("w1", METRIC_PEAK_RSS_BYTES, (1.0,) * 5),
        ]

        (violation,) = measurement_violations(rows, ("w1",), self.METRICS, 5)

        assert violation.rule is ViolationRule.too_few_runs
        assert violation.message == (
            f"metric {METRIC_WALL_TIME_S} on workload w1: "
            "3 runs measured; at least 5 required"
        )

    def test_non_objective_metrics_and_unknown_workloads_are_exempt(self) -> None:
        """
        GIVEN val_loss missing on w2 and duplicated on w1 with two runs,
              and an objective measurement on a workload nobody asked about
        WHEN measurement_violations checks wall time only
        THEN there is no violation
        """
        rows = [
            _measurement("w1", METRIC_WALL_TIME_S, (1.0,) * 5),
            _measurement("w2", METRIC_WALL_TIME_S, (1.0,) * 5),
            _measurement("w1", VAL_LOSS, (0.5, 0.5), unit=""),
            _measurement("w1", VAL_LOSS, (0.5, 0.5), unit=""),
            _measurement("elsewhere", METRIC_WALL_TIME_S, (1.0,)),
        ]

        assert (
            measurement_violations(rows, ("w1", "w2"), (METRIC_WALL_TIME_S,), 5) == ()
        )

    def test_violations_follow_workload_then_metric_order(self) -> None:
        """
        GIVEN nothing measured on two workloads for two metrics
        WHEN measurement_violations checks them (metrics repeated in the input)
        THEN four missing_measurement violations come in workload, metric order
        """
        metrics = (*self.METRICS, METRIC_WALL_TIME_S)

        violations = measurement_violations((), ("w1", "w2", "w1"), metrics, 5)

        assert [v.message for v in violations] == [
            f"metric {metric} was not measured on workload {workload}"
            for workload in ("w1", "w2")
            for metric in self.METRICS
        ]


# ---------------------------------------------------------------------------
# profile, research
# ---------------------------------------------------------------------------


class TestProfile:
    def test_copies_context_hotspots(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_project: Project,
        sample_workload: Workload,
    ) -> None:
        """
        GIVEN a context with two hotspots (the profiler stub)
        WHEN profile runs
        THEN the state gets them as a list and the event counts them
        """
        hotspots = (
            _hotspot(sample_project, sample_workload, "hot_loop"),
            _hotspot(sample_project, sample_workload, "frozen_encoder"),
        )

        delta = make_nodes(make_context(hotspots=hotspots))["profile"](base_state)

        assert _items(delta, "hotspots", Hotspot) == list(hotspots)
        assert _only_event(delta).data == {"hotspots": 2}


class TestResearch:
    def test_copies_context_techniques_and_finds_no_papers(
        self, make_context: ContextFactory, base_state: EngineState
    ) -> None:
        """
        GIVEN a context with one playbook technique (the research stub)
        WHEN research runs
        THEN techniques are copied, papers are empty and the event counts both
        """
        technique = Technique(
            slug="cache-frozen-encoder",
            name="Cache frozen encoder outputs",
            summary="Memoise a frozen encoder's embeddings across epochs.",
            change_class=ChangeClass.efficiency,
            expected_gain=0.4,
            provability=0.9,
            risk=0.1,
        )

        delta = make_nodes(make_context(techniques=(technique,)))["research"](
            base_state
        )

        assert _items(delta, "techniques", Technique) == [technique]
        assert delta["papers"] == []
        assert _only_event(delta).data == {"techniques": 1, "papers": 0}


# ---------------------------------------------------------------------------
# hypotheses
# ---------------------------------------------------------------------------


class TestHypotheses:
    def test_ranks_and_slices_candidates_and_starts_a_round(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
        h3_noise: Hypothesis,
        h4_behaviour: Hypothesis,
    ) -> None:
        """
        GIVEN three candidates and two hypotheses per round
        WHEN hypotheses runs on round 0
        THEN round becomes 1 and the two best candidates come back scored
        """
        ctx = make_context(
            [h3_noise, h1_cache, h4_behaviour], max_hypotheses_per_round=2
        )

        delta = make_nodes(ctx)["hypotheses"](base_state)

        assert delta["round"] == 1
        ranked = _items(delta, "hypotheses", Hypothesis)
        assert [h.title for h in ranked] == [h1_cache.title, h4_behaviour.title]
        assert all(h.status is HypothesisStatus.proposed for h in ranked)
        assert ranked[0].score > ranked[1].score > 0
        event = _only_event(delta)
        assert event.message == "round 1: ranked 2 of 3 candidates"
        assert event.data == {"round": 1, "ranked": 2, "candidates": 3}

    def test_skips_candidates_already_trialled_and_keeps_earlier_hypotheses(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
        h3_noise: Hypothesis,
    ) -> None:
        """
        GIVEN H1 was trialled in round 1
        WHEN hypotheses runs for round 2
        THEN only H3 is ranked and H1 is carried forward with its status
        """
        ctx = make_context([h1_cache, h3_noise], max_hypotheses_per_round=1)
        nodes = make_nodes(ctx)
        state = _advance(nodes, base_state, _before("combine"))
        assert state["round"] == 1
        assert [t.hypothesis_id for t in state["trials"]] == [h1_cache.id]

        delta = nodes["hypotheses"](state)

        assert delta["round"] == 2
        hypotheses = _items(delta, "hypotheses", Hypothesis)
        assert [h.id for h in hypotheses] == [h1_cache.id, h3_noise.id]
        assert hypotheses[0].status is HypothesisStatus.kept
        assert hypotheses[1].status is HypothesisStatus.proposed
        assert _only_event(delta).message == "round 2: ranked 1 of 1 candidates"

    def test_ranked_copies_are_proposed_whatever_the_candidate_status(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN a candidate that arrives with status inconclusive (re-proposed
              from a lesson, say)
        WHEN hypotheses runs
        THEN its ranked copy is proposed, so the trials node will run it
        """
        stale = h1_cache.model_copy(update={"status": HypothesisStatus.inconclusive})

        delta = make_nodes(make_context([stale]))["hypotheses"](base_state)

        (ranked,) = _items(delta, "hypotheses", Hypothesis)
        assert ranked.id == stale.id
        assert ranked.status is HypothesisStatus.proposed

    def test_candidates_already_in_state_are_not_ranked_again(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
        h3_noise: Hypothesis,
    ) -> None:
        """
        GIVEN H1 already in the state's hypotheses but never trialled
        WHEN hypotheses runs
        THEN H1 is carried once, unchanged, and only H3 is ranked
        """
        base_state["hypotheses"] = [h1_cache]

        delta = make_nodes(make_context([h1_cache, h3_noise]))["hypotheses"](base_state)

        hypotheses = _items(delta, "hypotheses", Hypothesis)
        assert [h.id for h in hypotheses] == [h1_cache.id, h3_noise.id]
        assert hypotheses[0] is h1_cache
        assert _only_event(delta).data["candidates"] == 1

    def test_lessons_in_the_repository_change_the_order(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_project: Project,
        h3_noise: Hypothesis,
    ) -> None:
        """
        GIVEN two equal candidates and a keep lesson about the second one
        WHEN hypotheses runs
        THEN the second candidate is ranked first
        """
        twin = h3_noise.model_copy(update={"id": "twin", "title": "Twin tweak"})
        ctx = make_context([h3_noise, twin])
        ctx.repository.save_lesson(
            Lesson(
                project_id=sample_project.id,
                hypothesis_id=twin.id,
                outcome=VerdictOutcome.keep,
                text="twin tweak kept last time",
            )
        )

        delta = make_nodes(ctx)["hypotheses"](base_state)

        assert [h.id for h in _items(delta, "hypotheses", Hypothesis)] == [
            twin.id,
            h3_noise.id,
        ]


# ---------------------------------------------------------------------------
# trials
# ---------------------------------------------------------------------------


class TestTrialBriefHotspots:
    """Which profiler hotspots a trial's editor is shown (``TrialBrief``)."""

    @staticmethod
    def _brief_hotspots(
        make_context: ContextFactory,
        base_state: EngineState,
        hypothesis: Hypothesis,
        hotspots: Sequence[Hotspot],
        scripts: dict[str, ScriptedOutcome],
    ) -> tuple[Hotspot, ...]:
        runner = StubTrialRunner(scripts)
        nodes = make_nodes(
            make_context([hypothesis], runner=runner, hotspots=tuple(hotspots))
        )
        nodes["trials"](_advance(nodes, base_state, _before("trials")))
        assert len(runner.briefs) == 1
        return runner.briefs[0].hotspots

    def test_the_fallback_is_at_most_five_hotspots(self) -> None:
        assert BRIEF_FALLBACK_HOTSPOTS == 5

    def test_named_and_matching_ids_give_only_those_in_profile_order(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_project: Project,
        sample_workload: Workload,
        h1_cache: Hypothesis,
        design_scripts: dict[str, ScriptedOutcome],
    ) -> None:
        """
        GIVEN seven profiled hotspots and a hypothesis naming two low-share
              ones (in reverse order) plus an id from another run
        WHEN trials runs it
        THEN the brief holds exactly the two named hotspots, in profile order
        """
        spots = _spots(
            sample_project, sample_workload, 0.05, 0.4, 0.02, 0.2, 0.1, 0.15, 0.08
        )
        named = (spots[6].id, "old-run-spot", spots[2].id)
        hypothesis = h1_cache.model_copy(update={"hotspot_ids": named})

        got = self._brief_hotspots(
            make_context, base_state, hypothesis, spots, design_scripts
        )

        assert got == (spots[2], spots[6])

    def test_stale_ids_give_the_top_five_by_share(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_project: Project,
        sample_workload: Workload,
        h1_cache: Hypothesis,
        design_scripts: dict[str, ScriptedOutcome],
    ) -> None:
        """
        GIVEN seven profiled hotspots and a hypothesis generated in an earlier
              run, whose hotspot_ids name none of them
        WHEN trials runs it
        THEN the brief holds this run's five largest-share hotspots, largest
             first
        """
        spots = _spots(
            sample_project, sample_workload, 0.05, 0.4, 0.02, 0.2, 0.1, 0.15, 0.08
        )
        hypothesis = h1_cache.model_copy(
            update={"hotspot_ids": ("old-run-a", "old-run-b")}
        )

        got = self._brief_hotspots(
            make_context, base_state, hypothesis, spots, design_scripts
        )

        assert got == (spots[1], spots[3], spots[5], spots[4], spots[6])

    def test_no_named_ids_give_the_top_five_by_share(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_project: Project,
        sample_workload: Workload,
        h1_cache: Hypothesis,
        design_scripts: dict[str, ScriptedOutcome],
    ) -> None:
        """
        GIVEN six profiled hotspots and a caller-built candidate naming none
        WHEN trials runs it
        THEN the brief holds the five largest-share hotspots, largest first
        """
        spots = _spots(sample_project, sample_workload, 0.1, 0.3, 0.01, 0.2, 0.05, 0.25)
        hypothesis = h1_cache.model_copy(update={"hotspot_ids": ()})

        got = self._brief_hotspots(
            make_context, base_state, hypothesis, spots, design_scripts
        )

        assert got == (spots[1], spots[5], spots[3], spots[0], spots[4])

    def test_fewer_than_five_hotspots_are_all_given(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_project: Project,
        sample_workload: Workload,
        h1_cache: Hypothesis,
        design_scripts: dict[str, ScriptedOutcome],
    ) -> None:
        """
        GIVEN three profiled hotspots and a candidate naming none
        WHEN trials runs it
        THEN the brief holds all three, largest share first
        """
        spots = _spots(sample_project, sample_workload, 0.2, 0.5, 0.3)
        hypothesis = h1_cache.model_copy(update={"hotspot_ids": ()})

        got = self._brief_hotspots(
            make_context, base_state, hypothesis, spots, design_scripts
        )

        assert got == (spots[1], spots[2], spots[0])

    @pytest.mark.parametrize("hotspot_ids", [(), ("old-run-spot",)])
    def test_no_hotspots_give_an_empty_tuple(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
        design_scripts: dict[str, ScriptedOutcome],
        hotspot_ids: tuple[str, ...],
    ) -> None:
        """
        GIVEN a run whose profile found no hotspots
        WHEN trials runs a candidate, naming ids or not
        THEN the brief's hotspots are an empty tuple
        """
        hypothesis = h1_cache.model_copy(update={"hotspot_ids": hotspot_ids})

        got = self._brief_hotspots(
            make_context, base_state, hypothesis, (), design_scripts
        )

        assert got == ()

    def test_ties_keep_profile_order(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_project: Project,
        sample_workload: Workload,
        h1_cache: Hypothesis,
        design_scripts: dict[str, ScriptedOutcome],
    ) -> None:
        """
        GIVEN seven hotspots where several share the same share, one of them
              tied across the fifth-place cut
        WHEN trials runs a candidate naming none
        THEN equal shares keep the profile's order, also at the cut
        """
        spots = _spots(
            sample_project, sample_workload, 0.1, 0.3, 0.1, 0.3, 0.1, 0.05, 0.1
        )
        hypothesis = h1_cache.model_copy(update={"hotspot_ids": ()})

        got = self._brief_hotspots(
            make_context, base_state, hypothesis, spots, design_scripts
        )

        assert got == (spots[1], spots[3], spots[0], spots[2], spots[4])


class TestTrials:
    def test_runs_every_proposed_hypothesis_on_its_own_branch(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
        h4_behaviour: Hypothesis,
    ) -> None:
        """
        GIVEN two proposed hypotheses after round 1 ranking
        WHEN trials runs
        THEN each gets an unjudged trial on engine/trial-<run id>-<hypothesis id>
             in round_trials (not on the judged trials channel), saved in the
             repository; costs are summed and the hypotheses become trialled
        """
        ctx = make_context([h1_cache, h4_behaviour])
        nodes = make_nodes(ctx)
        state = _advance(nodes, base_state, _before("trials"))

        delta = nodes["trials"](state)

        assert "trials" not in delta
        trials = _items(delta, "round_trials", Trial)
        assert [t.hypothesis_id for t in trials] == [h1_cache.id, h4_behaviour.id]
        assert [t.branch for t in trials] == [
            f"engine/trial-{RUN_ID}-{h1_cache.id}",
            f"engine/trial-{RUN_ID}-{h4_behaviour.id}",
        ]
        assert all(t.round == 1 for t in trials)
        assert all(t.judge_results == () for t in trials)
        assert ctx.repository.list_trials(RUN_ID) == tuple(trials)
        assert delta["cost_usd"] == pytest.approx(0.12 + 0.10)
        assert delta["tokens_used"] == 3400 + 2800
        hypotheses = _items(delta, "hypotheses", Hypothesis)
        assert [h.status for h in hypotheses] == [HypothesisStatus.trialled] * 2
        event = _only_event(delta)
        assert event.data == {
            "round": 1,
            "trials": 2,
            "failed": 0,
            "cost_usd": pytest.approx(0.22),
            "tokens_used": 6200,
        }

    def test_accumulates_cost_and_skips_hypotheses_already_decided(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
        h3_noise: Hypothesis,
    ) -> None:
        """
        GIVEN round 2 with H1 already kept and H3 newly proposed
        WHEN trials runs
        THEN only H3 is run, the delta holds that one trial and cost adds up
        """
        ctx = make_context([h1_cache, h3_noise], max_hypotheses_per_round=1)
        nodes = make_nodes(ctx)
        state = _advance(nodes, base_state, (*_before("combine"), "hypotheses"))
        assert state["round"] == 2

        delta = nodes["trials"](state)

        trials = _items(delta, "round_trials", Trial)
        assert [t.hypothesis_id for t in trials] == [h3_noise.id]
        assert trials[0].round == 2
        assert delta["cost_usd"] == pytest.approx(0.12 + 0.05)
        assert delta["tokens_used"] == 3400 + 1200
        assert len(ctx.repository.list_trials(RUN_ID)) == 2

    def test_passes_the_remaining_budget_and_a_brief_to_the_runner(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_project: Project,
        sample_workload: Workload,
        h1_cache: Hypothesis,
        design_scripts: dict[str, ScriptedOutcome],
    ) -> None:
        """
        GIVEN a 1.00 USD cap with 0.25 USD already spent, an understanding,
              two profiled hotspots of which H1 targets one, and an extra
              protected harness path from connect
        WHEN trials runs H1
        THEN the runner gets budget_usd 0.75 and a brief carrying the
             understanding, only H1's hotspot, and the context's protected
             patterns followed by the extra ones
        """
        mine = _hotspot(sample_project, sample_workload, "mine")
        other = _hotspot(sample_project, sample_workload, "other")
        hypothesis = h1_cache.model_copy(update={"hotspot_ids": (mine.id,)})
        understanding = ProjectUnderstanding(
            language="python", summary="a VLM bridge", served_by_model="m"
        )
        runner = StubTrialRunner(design_scripts)
        ctx = make_context([hypothesis], runner=runner, hotspots=(mine, other))
        nodes = make_nodes(ctx)
        state = _advance(nodes, base_state, _before("trials"))
        state = cast(
            EngineState,
            {
                **state,
                "max_cost_usd": 1.0,
                "cost_usd": 0.25,
                "understanding": understanding,
                "extra_protected": ["run.sh"],
            },
        )

        nodes["trials"](state)

        assert runner.budgets == [pytest.approx(0.75)]
        assert runner.briefs == [
            TrialBrief(
                understanding=understanding,
                hotspots=(mine,),
                protected=(*DEFAULT_PROTECTED_PATTERNS, "run.sh"),
            )
        ]

    def test_a_hypothesis_naming_none_of_this_runs_hotspots_is_unchanged(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_project: Project,
        sample_workload: Workload,
        h1_cache: Hypothesis,
        design_scripts: dict[str, ScriptedOutcome],
    ) -> None:
        """
        GIVEN a candidate whose hotspot_ids belong to an earlier run
        WHEN trials runs it with the top hotspots as the brief's fallback
        THEN the hypothesis in the state still carries its own ids, and the
             runner got that hypothesis, not a copy with this run's ids
        """
        spots = _spots(sample_project, sample_workload, 0.3, 0.6)
        hypothesis = h1_cache.model_copy(update={"hotspot_ids": ("old-run-spot",)})
        runner = _BriefRecordingRunner(StubTrialRunner(design_scripts))
        nodes = make_nodes(
            make_context([hypothesis], runner=runner, hotspots=tuple(spots))
        )
        state = _advance(nodes, base_state, _before("trials"))

        nodes["trials"](state)

        assert runner.hypotheses == [state["hypotheses"][0]]
        assert state["hypotheses"][0].hotspot_ids == ("old-run-spot",)
        assert runner.briefs[0].hotspots == (spots[1], spots[0])

    def test_an_overspent_run_starts_no_trial(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
        design_scripts: dict[str, ScriptedOutcome],
    ) -> None:
        """
        GIVEN a run that already spent more than its cap
        WHEN trials runs with H1 proposed
        THEN (Step 2, decision 10) no trial starts: the runner is never
             called, the round has no trials, the budget is marked exhausted
             and nothing more is charged
        """
        runner = StubTrialRunner(design_scripts)
        nodes = make_nodes(make_context([h1_cache], runner=runner))
        state = _advance(nodes, base_state, _before("trials"))
        state = cast(EngineState, {**state, "max_cost_usd": 0.5, "cost_usd": 0.6})

        delta = nodes["trials"](state)

        assert runner.budgets == []
        assert _items(delta, "round_trials", Trial) == []
        assert delta["budget_exhausted"] is True
        assert delta["cost_usd"] == pytest.approx(0.6)
        (exhausted,) = [e for e in _events(delta) if e.data.get("code")]
        assert exhausted.data["code"] == "budget_exhausted"
        assert exhausted.data["remaining_usd"] == 0.0

    def test_a_stub_trial_over_its_budget_fails_without_overcharging(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
        design_scripts: dict[str, ScriptedOutcome],
    ) -> None:
        """
        GIVEN 0.05 USD left and H1 scripted to cost 0.12 USD
        WHEN trials runs H1
        THEN the runner is offered the 0.05 left, the stub fails the trial
             for exceeding it and charges exactly the budget, never more
        """
        runner = StubTrialRunner(design_scripts)
        nodes = make_nodes(make_context([h1_cache], runner=runner))
        state = _advance(nodes, base_state, _before("trials"))
        state = cast(EngineState, {**state, "max_cost_usd": 0.5, "cost_usd": 0.45})

        delta = nodes["trials"](state)

        assert runner.budgets == [pytest.approx(0.05)]
        trial = _items(delta, "round_trials", Trial)[0]
        assert trial.error == OVER_BUDGET_ERROR
        assert trial.cost_usd == pytest.approx(0.05)
        assert delta["cost_usd"] == pytest.approx(0.5)

    def test_counts_failed_trials(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN a hypothesis whose trial errors out
        WHEN trials runs
        THEN the trial is recorded as failed and the event counts it
        """
        scripts = {h1_cache.title: ScriptedOutcome(error="SyntaxError", cost_usd=0.02)}
        nodes = make_nodes(make_context([h1_cache], scripts))
        state = _advance(nodes, base_state, _before("trials"))

        delta = nodes["trials"](state)

        assert _items(delta, "round_trials", Trial)[0].error == "SyntaxError"
        assert _only_event(delta).data["failed"] == 1

    def test_trial_branches_carry_full_ids_so_they_never_collide(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
        h3_noise: Hypothesis,
    ) -> None:
        """
        GIVEN two hypotheses whose ids share their first eight characters
        WHEN trials runs both
        THEN their branches differ, each naming the full run and hypothesis ids
        """
        first = h1_cache.model_copy(update={"id": "playbook-cache-a"})
        second = h3_noise.model_copy(update={"id": "playbook-cache-b"})
        nodes = make_nodes(make_context([first, second]))
        state = _advance(nodes, base_state, _before("trials"))

        trials = _items(nodes["trials"](state), "round_trials", Trial)

        assert [t.branch for t in trials] == [
            f"engine/trial-{RUN_ID}-playbook-cache-a",
            f"engine/trial-{RUN_ID}-playbook-cache-b",
        ]

    @pytest.mark.parametrize("prefix", ["", "engine", "engine/../"])
    def test_refuses_an_unsafe_branch_prefix_before_running_anything(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
        prefix: str,
    ) -> None:
        """
        GIVEN a context whose branch prefix is empty, slash-less or traversing
        WHEN trials runs
        THEN a DeliveryError refuses the trial branch and the runner is never called
        """
        runner = StubTrialRunner({h1_cache.id: ScriptedOutcome()})
        nodes = make_nodes(
            make_context([h1_cache], runner=runner, branch_prefix=prefix)
        )
        state = _advance(nodes, base_state, _before("trials"))

        with pytest.raises(DeliveryError):
            nodes["trials"](state)
        assert runner.calls == []

    @pytest.mark.parametrize(
        ("update", "problem"),
        [
            pytest.param(
                {"hypothesis_id": "someone-else"}, "hypothesis_id", id="hypothesis"
            ),
            pytest.param({"round": 2}, "round is 2, expected 1", id="round"),
            pytest.param(
                {"status": TrialStatus.pending}, "status is pending", id="pending"
            ),
            pytest.param(
                {"status": TrialStatus.running}, "status is running", id="running"
            ),
            pytest.param(
                {"status": TrialStatus.rejected}, "status is rejected", id="rejected"
            ),
            pytest.param(
                {
                    "judge_results": (
                        JudgeResult(
                            judge="speed",
                            outcome=JudgeOutcome.passed,
                            reason="judged by the runner itself",
                        ),
                    )
                },
                "judge_results",
                id="pre-judged",
            ),
        ],
    )
    def test_refuses_a_trial_the_runner_reports_inconsistently(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
        design_scripts: dict[str, ScriptedOutcome],
        update: dict[str, object],
        problem: str,
    ) -> None:
        """
        GIVEN a runner whose Trial names another hypothesis or round, is not
              measured or failed, or arrives already judged
        WHEN trials runs
        THEN an EngineError names the problem and nothing is saved
        """
        runner = _TamperingRunner(StubTrialRunner(design_scripts), update)
        ctx = make_context([h1_cache], runner=runner)
        nodes = make_nodes(ctx)
        state = _advance(nodes, base_state, _before("trials"))

        with pytest.raises(EngineError, match=problem):
            nodes["trials"](state)
        assert ctx.repository.list_trials(RUN_ID) == ()

    def test_requires_a_baseline(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN a state whose baseline is None
        WHEN trials runs
        THEN an EngineError names the missing baseline
        """
        nodes = make_nodes(make_context([h1_cache]))
        state = _advance(nodes, base_state, ("hypotheses",))

        with pytest.raises(EngineError, match="baseline"):
            nodes["trials"](state)


# ---------------------------------------------------------------------------
# judges
# ---------------------------------------------------------------------------


class TestJudges:
    def test_enriches_this_rounds_trials_with_active_judges(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN a measured round-1 trial for a runtime objective
        WHEN judges runs
        THEN the judged copy (results from the judges that apply, no memory
             judge) is appended to the trials channel, replaces round_trials
             and replaces the repository row
        """
        ctx = make_context([h1_cache])
        nodes = make_nodes(ctx)
        state = _advance(nodes, base_state, _before("judges"))
        (unjudged,) = state["round_trials"]
        assert state["trials"] == []

        delta = nodes["judges"](state)

        (judged,) = _items(delta, "trials", Trial)
        assert _items(delta, "round_trials", Trial) == [judged]
        assert judged.id == unjudged.id
        assert [r.judge for r in judged.judge_results] == [
            "speed",
            "equivalence",
            "guardrail",
            "tests",
        ]
        assert ctx.repository.list_trials(RUN_ID) == (judged,)
        event = _only_event(delta)
        assert event.data == {
            "round": 1,
            "trials": 1,
            "judges": "speed, equivalence, guardrail, tests",
        }

    def test_leaves_earlier_rounds_alone(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
        h3_noise: Hypothesis,
    ) -> None:
        """
        GIVEN round 2 with a judged round-1 trial and one fresh trial
        WHEN judges runs
        THEN only the round-2 trial is judged and appended
        """
        ctx = make_context([h3_noise, h1_cache], max_hypotheses_per_round=1)
        nodes = make_nodes(ctx)
        state = _advance(
            nodes, base_state, (*_before("combine"), "hypotheses", "trials")
        )
        (round_one,) = state["trials"]
        assert round_one.round == 1 and len(round_one.judge_results) == 4

        delta = nodes["judges"](state)

        (judged,) = _items(delta, "trials", Trial)
        assert judged.round == 2 and len(judged.judge_results) == 4
        first, second = ctx.repository.list_trials(RUN_ID)
        assert first == round_one
        assert second == judged

    def test_requires_a_baseline(
        self, make_context: ContextFactory, base_state: EngineState
    ) -> None:
        """
        GIVEN a state whose baseline is None
        WHEN judges runs
        THEN an EngineError names the missing baseline
        """
        with pytest.raises(EngineError, match="baseline"):
            make_nodes(make_context())["judges"](base_state)


# ---------------------------------------------------------------------------
# verdicts
# ---------------------------------------------------------------------------


class TestVerdicts:
    def test_design_truth_table(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
        h2_protected: Hypothesis,
        h3_noise: Hypothesis,
        h4_behaviour: Hypothesis,
    ) -> None:
        """
        GIVEN the four design hypotheses judged in one round
        WHEN verdicts runs
        THEN H1 keep, H2 reject (protected path), H3 inconclusive,
             H4 needs_approval; statuses, pending ids and repository follow
        """
        ctx = make_context(
            [h1_cache, h2_protected, h3_noise, h4_behaviour],
            max_hypotheses_per_round=4,
        )
        nodes = make_nodes(ctx)
        state = _advance(nodes, base_state, _before("verdicts"))

        delta = nodes["verdicts"](state)

        verdicts = {v.hypothesis_id: v for v in _items(delta, "verdicts", Verdict)}
        assert verdicts[h1_cache.id].outcome is VerdictOutcome.keep
        assert verdicts[h1_cache.id].gain == pytest.approx(0.4167, abs=1e-3)
        assert verdicts[h2_protected.id].outcome is VerdictOutcome.reject
        assert [v.rule for v in verdicts[h2_protected.id].violations] == [
            ViolationRule.protected_path
        ]
        assert verdicts[h3_noise.id].outcome is VerdictOutcome.inconclusive
        assert verdicts[h4_behaviour.id].outcome is VerdictOutcome.needs_approval
        assert verdicts[h4_behaviour.id].change_class is ChangeClass.behaviour
        statuses = {h.id: h.status for h in _items(delta, "hypotheses", Hypothesis)}
        assert statuses == {
            h1_cache.id: HypothesisStatus.kept,
            h2_protected.id: HypothesisStatus.rejected,
            h3_noise.id: HypothesisStatus.inconclusive,
            h4_behaviour.id: HypothesisStatus.trialled,
        }
        assert delta["pending_approval_ids"] == [verdicts[h4_behaviour.id].id]
        assert {v.id for v in ctx.repository.list_verdicts(RUN_ID)} == {
            v.id for v in verdicts.values()
        }
        assert all(len(v.judge_results) == 4 for v in verdicts.values())
        event = _only_event(delta)
        assert event.data == {
            "round": 1,
            "verdicts": 4,
            "keep": 1,
            "reject": 1,
            "inconclusive": 1,
            "needs_approval": 1,
        }

    def test_too_few_runs_on_an_objective_metric_rejects(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN a trial measured over three wall-time runs
        WHEN verdicts runs
        THEN the verdict is reject with a too_few_runs violation
        """
        scripts = {
            h1_cache.title: ScriptedOutcome(
                samples={METRIC_WALL_TIME_S: (1.0, 1.0, 1.0), VAL_LOSS: (0.5,) * 5},
                tests_passed=True,
            )
        }
        nodes = make_nodes(make_context([h1_cache], scripts))
        state = _advance(nodes, base_state, _before("verdicts"))

        (verdict,) = _items(nodes["verdicts"](state), "verdicts", Verdict)

        assert verdict.outcome is VerdictOutcome.reject
        assert [v.rule for v in verdict.violations] == [ViolationRule.too_few_runs]

    def test_run_count_rule_exempts_guardrail_and_test_metrics(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN a trial with two val_loss runs and the single-run tests_passed flag
        WHEN verdicts runs
        THEN no run-count violation is raised and the trial is kept
        """
        scripts = {
            h1_cache.title: ScriptedOutcome(
                touched_paths=("src/bridge/encoder.py",),
                samples={METRIC_WALL_TIME_S: (1.05,) * 5, VAL_LOSS: (0.5, 0.5)},
                tests_passed=True,
            )
        }
        nodes = make_nodes(make_context([h1_cache], scripts))
        state = _advance(nodes, base_state, _before("verdicts"))

        (verdict,) = _items(nodes["verdicts"](state), "verdicts", Verdict)

        assert verdict.violations == ()
        assert verdict.outcome is VerdictOutcome.keep

    def test_only_this_rounds_trials_get_verdicts(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
        h3_noise: Hypothesis,
    ) -> None:
        """
        GIVEN round 2 (H3, ranked second) with H1's round-1 verdict in state
        WHEN verdicts runs
        THEN the delta holds the round-2 verdict only
        """
        ctx = make_context([h3_noise, h1_cache], max_hypotheses_per_round=1)
        nodes = make_nodes(ctx)
        state = _advance(
            nodes, base_state, (*_before("combine"), "hypotheses", "trials", "judges")
        )
        assert [v.hypothesis_id for v in state["verdicts"]] == [h1_cache.id]

        delta = nodes["verdicts"](state)

        (verdict,) = _items(delta, "verdicts", Verdict)
        assert verdict.hypothesis_id == h3_noise.id
        assert len(ctx.repository.list_verdicts(RUN_ID)) == 2

    def test_reads_the_judged_trials_from_state_not_the_repository(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN H1 judged in round 1, and a verdicts node whose repository is
              fresh (a resume in another process)
        WHEN verdicts runs
        THEN H1 is still kept: the judge results come from round_trials
        """
        ctx = make_context([h1_cache])
        state = _advance(make_nodes(ctx), base_state, _before("verdicts"))
        fresh = replace(ctx, repository=InMemoryRepository())

        (verdict,) = _items(make_nodes(fresh)["verdicts"](state), "verdicts", Verdict)

        assert verdict.outcome is VerdictOutcome.keep
        assert verdict.trial_id == state["round_trials"][0].id
        assert fresh.repository.list_verdicts(RUN_ID) == (verdict,)

    def test_ignores_trials_that_are_not_in_round_trials(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN an orphan round-1 trial in the repository (left by a trials node
              that failed part-way and was re-executed)
        WHEN verdicts runs
        THEN only the trial in round_trials gets a verdict
        """
        ctx = make_context([h1_cache])
        nodes = make_nodes(ctx)
        state = _advance(nodes, base_state, _before("verdicts"))
        ctx.repository.save_trial(RUN_ID, Trial(hypothesis_id=h1_cache.id, round=1))

        (verdict,) = _items(nodes["verdicts"](state), "verdicts", Verdict)

        assert verdict.trial_id == state["round_trials"][0].id

    def test_an_omitted_secondary_objective_metric_rejects(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_project: Project,
        sample_objective: Objective,
        baseline_script: ScriptedOutcome,
        h1_cache: Hypothesis,
        design_scripts: dict[str, ScriptedOutcome],
    ) -> None:
        """
        GIVEN runtime and peak-memory objectives, both measured at baseline,
              and H1's trial that reports wall time but omits peak memory
        WHEN verdicts runs
        THEN the verdict is reject with a missing_measurement violation, not keep
        """
        memory = Objective(
            project_id=sample_project.id,
            kind=ObjectiveKind.peak_memory,
            metric=METRIC_PEAK_RSS_BYTES,
            direction=Direction.minimize,
            weight=0.5,
            description="memory must not regress",
        )
        base_state["objectives"] = [sample_objective, memory]
        with_memory = replace(
            baseline_script,
            samples={**baseline_script.samples, METRIC_PEAK_RSS_BYTES: (1e9,) * 5},
        )
        ctx = make_context([h1_cache], baseline_runner=StubBaselineRunner(with_memory))
        nodes = make_nodes(ctx)
        state = _advance(nodes, base_state, _before("verdicts"))
        assert METRIC_PEAK_RSS_BYTES not in design_scripts[h1_cache.title].samples

        (verdict,) = _items(nodes["verdicts"](state), "verdicts", Verdict)

        assert verdict.outcome is VerdictOutcome.reject
        assert [v.rule for v in verdict.violations] == [
            ViolationRule.missing_measurement
        ]
        assert METRIC_PEAK_RSS_BYTES in verdict.violations[0].message

    def test_a_duplicate_objective_measurement_rejects(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        baseline_script: ScriptedOutcome,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN a trial that really runs 39 % slower but reports a fast copy of
              its wall-time measurement first
        WHEN verdicts runs
        THEN the verdict is reject with a duplicate_measurement violation
        """
        slow = ScriptedOutcome(
            touched_paths=("src/x.py",),
            samples={METRIC_WALL_TIME_S: (2.5,) * 5, VAL_LOSS: (0.5,) * 5},
            tests_passed=True,
            output_fingerprint=baseline_script.output_fingerprint,
        )
        runner = _CherryPickingRunner(StubTrialRunner({h1_cache.id: slow}))
        nodes = make_nodes(make_context([h1_cache], runner=runner))
        state = _advance(nodes, base_state, _before("verdicts"))

        (verdict,) = _items(nodes["verdicts"](state), "verdicts", Verdict)

        assert verdict.outcome is VerdictOutcome.reject
        assert [v.rule for v in verdict.violations] == [
            ViolationRule.duplicate_measurement
        ]

    def test_a_duplicate_guardrail_measurement_rejects(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        baseline_script: ScriptedOutcome,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN a 42 % faster trial whose val_loss really rose from 0.5 to 0.9
              (far past the 1 % guardrail) but which reports a healthy copy of
              the val_loss measurement first
        WHEN verdicts runs
        THEN the verdict is reject with a duplicate_measurement violation,
             never an automatic keep
        """
        worse = ScriptedOutcome(
            touched_paths=("src/x.py",),
            samples={METRIC_WALL_TIME_S: (1.05,) * 5, VAL_LOSS: (0.9,) * 5},
            tests_passed=True,
            output_fingerprint=baseline_script.output_fingerprint,
        )
        runner = _GuardrailDodgingRunner(StubTrialRunner({h1_cache.id: worse}))
        nodes = make_nodes(make_context([h1_cache], runner=runner))
        state = _advance(nodes, base_state, _before("verdicts"))

        (verdict,) = _items(nodes["verdicts"](state), "verdicts", Verdict)

        assert verdict.outcome is VerdictOutcome.reject
        assert [v.rule for v in verdict.violations] == [
            ViolationRule.duplicate_measurement
        ]
        assert VAL_LOSS in verdict.violations[0].message

    def test_a_failed_trial_is_rejected_for_failing(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN a trial that failed before measuring anything
        WHEN verdicts runs
        THEN it is rejected because it failed (its missing measurements are a
             consequence, not a violation)
        """
        scripts = {h1_cache.title: ScriptedOutcome(error="SyntaxError")}
        nodes = make_nodes(make_context([h1_cache], scripts))
        state = _advance(nodes, base_state, _before("verdicts"))

        (verdict,) = _items(nodes["verdicts"](state), "verdicts", Verdict)

        assert verdict.outcome is VerdictOutcome.reject
        assert verdict.violations == ()
        assert verdict.summary == "reject: trial failed: SyntaxError"

    def test_unknown_hypothesis_is_an_engine_error(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN a judged trial whose hypothesis is missing from the state
        WHEN verdicts runs
        THEN an EngineError names the hypothesis
        """
        nodes = make_nodes(make_context([h1_cache]))
        state = _advance(nodes, base_state, _before("verdicts"))
        state["hypotheses"] = []

        with pytest.raises(EngineError, match=h1_cache.id):
            nodes["verdicts"](state)


# ---------------------------------------------------------------------------
# after_verdicts routing
# ---------------------------------------------------------------------------


class TestAfterVerdicts:
    @staticmethod
    def _verdict(hypothesis: Hypothesis, outcome: VerdictOutcome) -> Verdict:
        return Verdict(
            trial_id="trial",
            hypothesis_id=hypothesis.id,
            outcome=outcome,
            change_class=hypothesis.change_class,
            summary=str(outcome),
        )

    @staticmethod
    def _trial(hypothesis: Hypothesis) -> Trial:
        return Trial(hypothesis_id=hypothesis.id, round=1)

    @pytest.mark.parametrize(
        ("pending", "outcome", "round_", "max_rounds", "trialled", "expected"),
        [
            pytest.param(
                True,
                VerdictOutcome.keep,
                3,
                3,
                True,
                "approval_gate",
                id="pending wins",
            ),
            pytest.param(
                True,
                VerdictOutcome.inconclusive,
                1,
                3,
                False,
                "approval_gate",
                id="pending beats untrialled candidates and spare rounds",
            ),
            pytest.param(False, VerdictOutcome.keep, 1, 3, False, "combine", id="keep"),
            pytest.param(
                False,
                VerdictOutcome.inconclusive,
                3,
                3,
                False,
                "combine",
                id="max rounds",
            ),
            pytest.param(
                False,
                VerdictOutcome.inconclusive,
                1,
                3,
                True,
                "combine",
                id="no candidates left",
            ),
            pytest.param(
                False,
                VerdictOutcome.inconclusive,
                1,
                3,
                False,
                "hypotheses",
                id="next round",
            ),
            pytest.param(
                False,
                VerdictOutcome.reject,
                2,
                3,
                False,
                "hypotheses",
                id="reject then next round",
            ),
        ],
    )
    def test_routing_table(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
        h3_noise: Hypothesis,
        pending: bool,
        outcome: VerdictOutcome,
        round_: int,
        max_rounds: int,
        trialled: bool,
        expected: str,
    ) -> None:
        """
        GIVEN pending approvals, a verdict outcome, the round counters and
              whether every candidate has been trialled
        WHEN after_verdicts routes
        THEN pending -> approval_gate, keep -> combine, exhausted rounds or
             candidates -> combine, otherwise -> hypotheses
        """
        ctx = make_context([h1_cache, h3_noise])
        verdict = self._verdict(h1_cache, outcome)
        base_state["verdicts"] = [verdict]
        base_state["pending_approval_ids"] = [verdict.id] if pending else []
        base_state["round"] = round_
        base_state["max_rounds"] = max_rounds
        others = [h3_noise] if trialled else []
        base_state["trials"] = [self._trial(h) for h in (h1_cache, *others)]

        assert make_router(ctx)(base_state) == expected


# ---------------------------------------------------------------------------
# approval_gate (needs a running graph for interrupt())
# ---------------------------------------------------------------------------


class TestApprovalGate:
    @pytest.fixture
    def pending_state(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h4_behaviour: Hypothesis,
    ) -> tuple[NodeContext, dict[str, NodeFn], EngineState]:
        ctx = make_context([h4_behaviour])
        nodes = make_nodes(ctx)
        state = _advance(nodes, base_state, _before("combine"))
        assert len(state["pending_approval_ids"]) == 1
        return ctx, nodes, state

    def test_interrupts_with_an_approval_request_built_from_state(
        self,
        pending_state: tuple[NodeContext, dict[str, NodeFn], EngineState],
        h4_behaviour: Hypothesis,
    ) -> None:
        """
        GIVEN a state with one verdict awaiting approval
        WHEN the gate node runs inside a graph
        THEN the run interrupts with an ApprovalRequest listing that verdict
        """
        _, nodes, state = pending_state
        graph = _single_node_graph(nodes["approval_gate"], "approval_gate")
        cfg = run_config(RUN_ID, 3)

        output = graph.invoke(state, cfg, version="v2")

        assert len(output.interrupts) == 1
        request = ApprovalRequest.model_validate(output.interrupts[0].value)
        assert request.run_id == RUN_ID
        (item,) = request.items
        assert item.verdict_id == state["pending_approval_ids"][0]
        assert item.title == h4_behaviour.title
        assert item.change_class is ChangeClass.behaviour
        assert item.gain == pytest.approx(0.1667, abs=1e-3)
        assert "needs_approval" in item.summary
        assert "1 change" in request.message
        assert request.error is None
        assert graph.get_state(cfg).next == ("approval_gate",)

    def test_resume_records_the_decision_and_approves_verdicts(
        self, pending_state: tuple[NodeContext, dict[str, NodeFn], EngineState]
    ) -> None:
        """
        GIVEN an interrupted gate
        WHEN the graph resumes with an approval decision
        THEN the state holds the decision, pending ids are cleared, the
             hypothesis is kept and the repository verdict is the decided copy:
             outcome keep with approver and note
        """
        ctx, nodes, state = pending_state
        graph = _single_node_graph(nodes["approval_gate"], "approval_gate")
        cfg = run_config(RUN_ID, 3)
        graph.invoke(state, cfg, version="v2")
        verdict_id = state["pending_approval_ids"][0]
        decision = ApprovalDecision(
            approved_verdict_ids=(verdict_id,), approver="praveen", note="ship it"
        )

        output = graph.invoke(
            Command(resume=decision.model_dump(mode="json")), cfg, version="v2"
        )

        assert output.interrupts == ()
        approval = output.value["approval"]
        assert approval is not None
        assert approval.approver == "praveen"
        assert approval.approved_verdict_ids == (verdict_id,)
        assert output.value["pending_approval_ids"] == []
        assert output.value["phase"] is RunPhase.approval
        (stored,) = ctx.repository.list_verdicts(RUN_ID)
        assert stored.id == verdict_id
        assert stored.outcome is VerdictOutcome.keep
        assert stored.approved_by == "praveen"
        assert stored.approval_note == "ship it"
        assert [h.status for h in output.value["hypotheses"]] == [HypothesisStatus.kept]
        event = output.value["events"][-1]
        assert event.phase is RunPhase.approval
        assert event.data == {"approver": "praveen", "approved": 1, "rejected": 0}

    def test_rejection_is_recorded_on_the_verdict_and_the_hypothesis(
        self, pending_state: tuple[NodeContext, dict[str, NodeFn], EngineState]
    ) -> None:
        """
        GIVEN an interrupted gate
        WHEN the graph resumes with a rejection and a note
        THEN the repository verdict becomes reject with the note (no approver),
             the hypothesis is rejected and the event counts it
        """
        ctx, nodes, state = pending_state
        graph = _single_node_graph(nodes["approval_gate"], "approval_gate")
        cfg = run_config(RUN_ID, 3)
        graph.invoke(state, cfg, version="v2")
        decision = ApprovalDecision(
            rejected_verdict_ids=(state["pending_approval_ids"][0],),
            approver="praveen",
            note="bf16 drifts too much",
        )

        output = graph.invoke(
            Command(resume=decision.model_dump(mode="json")), cfg, version="v2"
        )

        (stored,) = ctx.repository.list_verdicts(RUN_ID)
        assert stored.outcome is VerdictOutcome.reject
        assert stored.approved_by is None
        assert stored.approval_note == "bf16 drifts too much"
        assert [h.status for h in output.value["hypotheses"]] == [
            HypothesisStatus.rejected
        ]
        assert output.value["events"][-1].data["rejected"] == 1

    def test_an_undecided_verdict_is_left_as_it_was(
        self, pending_state: tuple[NodeContext, dict[str, NodeFn], EngineState]
    ) -> None:
        """
        GIVEN an interrupted gate
        WHEN the graph resumes with a decision that names no verdict at all
             (the human deferred)
        THEN the repository verdict still needs approval and the hypothesis
             keeps its trialled status
        """
        ctx, nodes, state = pending_state
        graph = _single_node_graph(nodes["approval_gate"], "approval_gate")
        cfg = run_config(RUN_ID, 3)
        graph.invoke(state, cfg, version="v2")
        before = ctx.repository.list_verdicts(RUN_ID)
        decision = ApprovalDecision(approver="pk", note="deferred")

        output = graph.invoke(
            Command(resume=decision.model_dump(mode="json")), cfg, version="v2"
        )

        assert ctx.repository.list_verdicts(RUN_ID) == before
        assert before[0].outcome is VerdictOutcome.needs_approval
        assert [h.status for h in output.value["hypotheses"]] == [
            HypothesisStatus.trialled
        ]
        assert output.value["events"][-1].data == {
            "approver": "pk",
            "approved": 0,
            "rejected": 0,
        }

    def test_an_invalid_decision_asks_again_with_the_error(
        self, pending_state: tuple[NodeContext, dict[str, NodeFn], EngineState]
    ) -> None:
        """
        GIVEN an interrupted gate
        WHEN the graph resumes with a payload that is not an ApprovalDecision,
             then with a valid one
        THEN the first resume interrupts again with the same request plus the
             validation error, and the second resume records the decision
        """
        ctx, nodes, state = pending_state
        graph = _single_node_graph(nodes["approval_gate"], "approval_gate")
        cfg = run_config(RUN_ID, 3)
        first = graph.invoke(state, cfg, version="v2")
        verdict_id = state["pending_approval_ids"][0]

        retry = graph.invoke(Command(resume={"approver": None}), cfg, version="v2")

        (asked_again,) = retry.interrupts
        request = ApprovalRequest.model_validate(asked_again.value)
        assert request.error is not None
        assert request.error.startswith("invalid approval decision: ")
        assert "approver" in request.error
        original = ApprovalRequest.model_validate(first.interrupts[0].value)
        assert request.model_copy(update={"error": None}) == original
        assert graph.get_state(cfg).next == ("approval_gate",)
        assert ctx.repository.list_verdicts(RUN_ID)[0].approved_by is None

        decision = ApprovalDecision(approved_verdict_ids=(verdict_id,), approver="pk")
        done = graph.invoke(
            Command(resume=decision.model_dump(mode="json")), cfg, version="v2"
        )

        assert done.interrupts == ()
        approval = done.value["approval"]
        assert approval is not None and approval.approver == "pk"
        (stored,) = ctx.repository.list_verdicts(RUN_ID)
        assert stored.outcome is VerdictOutcome.keep
        assert graph.get_state(cfg).next == ()

    def test_a_decision_naming_unknown_verdicts_asks_again(
        self, pending_state: tuple[NodeContext, dict[str, NodeFn], EngineState]
    ) -> None:
        """
        GIVEN an interrupted gate with one pending verdict
        WHEN the graph resumes with a well-formed decision that approves a
             verdict id the gate never offered (a typo), then with the right id
        THEN the first resume interrupts again naming the unknown id instead of
             finishing the run with nothing approved, and the second resume
             records the approval
        """
        ctx, nodes, state = pending_state
        graph = _single_node_graph(nodes["approval_gate"], "approval_gate")
        cfg = run_config(RUN_ID, 3)
        graph.invoke(state, cfg, version="v2")
        verdict_id = state["pending_approval_ids"][0]

        typo = ApprovalDecision(approved_verdict_ids=("typo",), approver="pk")
        retry = graph.invoke(
            Command(resume=typo.model_dump(mode="json")), cfg, version="v2"
        )

        (asked_again,) = retry.interrupts
        request = ApprovalRequest.model_validate(asked_again.value)
        assert request.error == "unknown verdict ids: typo"
        assert graph.get_state(cfg).next == ("approval_gate",)

        decision = ApprovalDecision(approved_verdict_ids=(verdict_id,), approver="pk")
        done = graph.invoke(
            Command(resume=decision.model_dump(mode="json")), cfg, version="v2"
        )

        assert done.interrupts == ()
        (stored,) = ctx.repository.list_verdicts(RUN_ID)
        assert stored.outcome is VerdictOutcome.keep


# ---------------------------------------------------------------------------
# combine
# ---------------------------------------------------------------------------


class TestCombine:
    def test_keeps_keep_verdicts_and_approved_ones(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
        h3_noise: Hypothesis,
        h4_behaviour: Hypothesis,
    ) -> None:
        """
        GIVEN a keep, an inconclusive and an approved needs_approval verdict
        WHEN combine runs
        THEN the kept ids are the keep verdict then the approved one
        """
        ctx = make_context(
            [h1_cache, h3_noise, h4_behaviour], max_hypotheses_per_round=3
        )
        nodes = make_nodes(ctx)
        state = _advance(nodes, base_state, _before("combine"))
        by_hypothesis = {v.hypothesis_id: v for v in state["verdicts"]}
        state["approval"] = ApprovalDecision(
            approved_verdict_ids=(
                by_hypothesis[h4_behaviour.id].id,
                by_hypothesis[h1_cache.id].id,  # already kept: not duplicated
                "unknown-verdict",  # ignored
            ),
            approver="praveen",
        )

        delta = nodes["combine"](state)

        assert delta["kept_verdict_ids"] == [
            by_hypothesis[h1_cache.id].id,
            by_hypothesis[h4_behaviour.id].id,
        ]
        assert _only_event(delta).data == {"kept": 2}

    def test_without_a_decision_only_keeps_count(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
        h4_behaviour: Hypothesis,
    ) -> None:
        """
        GIVEN a keep and an undecided needs_approval verdict
        WHEN combine runs with no approval
        THEN only the keep verdict is kept
        """
        nodes = make_nodes(make_context([h1_cache, h4_behaviour]))
        state = _advance(nodes, base_state, _before("combine"))
        keep = next(v for v in state["verdicts"] if v.outcome is VerdictOutcome.keep)

        assert nodes["combine"](state)["kept_verdict_ids"] == [keep.id]

    def test_a_rejected_verdict_is_not_kept(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
        h4_behaviour: Hypothesis,
    ) -> None:
        """
        GIVEN a keep verdict and a needs_approval verdict the human rejected
        WHEN combine runs
        THEN only the keep verdict is kept
        """
        nodes = make_nodes(make_context([h1_cache, h4_behaviour]))
        state = _advance(nodes, base_state, _before("combine"))
        by_hypothesis = {v.hypothesis_id: v for v in state["verdicts"]}
        state["approval"] = ApprovalDecision(
            rejected_verdict_ids=(by_hypothesis[h4_behaviour.id].id,), approver="pk"
        )

        assert nodes["combine"](state)["kept_verdict_ids"] == [
            by_hypothesis[h1_cache.id].id
        ]


# ---------------------------------------------------------------------------
# deliver
# ---------------------------------------------------------------------------


class TestDeliver:
    def test_report_only_when_nothing_was_kept(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h3_noise: Hypothesis,
    ) -> None:
        """
        GIVEN a run whose only verdict is inconclusive
        WHEN deliver runs
        THEN the delivery is report_only with a markdown report of every verdict
        """
        nodes = make_nodes(make_context([h3_noise]))
        state = _advance(nodes, base_state, _before("deliver"))

        delta = nodes["deliver"](state)

        delivery = delta["delivery"]
        assert isinstance(delivery, Delivery)
        assert delivery.kind is DeliveryKind.report_only
        assert delivery.branch is None
        assert delivery.verdict_ids == ()
        assert delivery.combined_diff == ""
        report = delivery.report_markdown
        assert report.startswith(f"# Engine run {RUN_ID[:8]}: bridge")
        assert "Baseline: wall_time_s mean 1.800 s over 5 run(s)" in report
        assert f"| {h3_noise.title} | inconclusive |" in report
        assert "Kept: nothing" in report
        assert _only_event(delta).data == {"kind": "report_only", "kept": 0}

    def test_branch_delivery_with_the_combined_diff(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN a kept verdict whose trial carries a diff
        WHEN deliver runs
        THEN the delivery targets engine/run-<full run id> with that diff and
             verdict id
        """
        nodes = make_nodes(make_context([h1_cache]))
        state = _advance(nodes, base_state, _before("deliver"))
        state["trials"] = [
            t.model_copy(update={"diff": "--- a/encoder.py\n+++ b/encoder.py"})
            for t in state["trials"]
        ]

        delta = nodes["deliver"](state)

        delivery = delta["delivery"]
        assert isinstance(delivery, Delivery)
        assert delivery.kind is DeliveryKind.branch
        assert delivery.branch == f"engine/run-{RUN_ID}"
        assert delivery.verdict_ids == tuple(state["kept_verdict_ids"])
        assert delivery.combined_diff == "--- a/encoder.py\n+++ b/encoder.py"
        assert delivery.project_id == state["project"].id
        assert f"| {h1_cache.title} | keep | +41.7% |" in delivery.report_markdown
        assert "Kept: " + h1_cache.title in delivery.report_markdown
        event = _only_event(delta)
        assert event.data == {"kind": "branch", "kept": 1, "branch": delivery.branch}

    def test_refuses_to_deliver_onto_the_default_branch(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN a project whose default branch equals the engine's delivery branch
        WHEN deliver runs with something kept
        THEN a DeliveryError refuses the delivery
        """
        nodes = make_nodes(make_context([h1_cache]))
        state = _advance(nodes, base_state, _before("deliver"))
        state["project"] = state["project"].model_copy(
            update={"default_branch": f"engine/run-{RUN_ID}"}
        )

        with pytest.raises(DeliveryError, match="default branch"):
            nodes["deliver"](state)

    @pytest.mark.parametrize(
        ("branch", "prefix", "message"),
        [
            pytest.param("main", "engine/", "default branch", id="default"),
            pytest.param(
                "feature/x", "engine/", "outside the engine prefix", id="outside"
            ),
            pytest.param("release", "", "prefix '' must", id="empty prefix"),
            pytest.param(
                "engine-x", "engine", "prefix 'engine' must", id="slashless prefix"
            ),
            pytest.param("engine/../main", "engine/", "contains '..'", id="parent"),
            pytest.param("engine/a..b", "engine/", "contains '..'", id="double dot"),
            pytest.param("engine/x.lock", "engine/", "ends with '.lock'", id="lock"),
            pytest.param("engine/@{-1}", "engine/", "'@{'", id="reflog"),
            pytest.param("engine//x", "engine/", "empty segment", id="empty segment"),
            pytest.param("engine/x/", "engine/", "empty segment", id="trailing slash"),
            pytest.param("engine/x.", "engine/", "ends with '.'", id="trailing dot"),
            pytest.param(
                "engine/.hidden", "engine/", "segment '.hidden'", id="dot first"
            ),
            pytest.param(
                "engine/x y~^:z", "engine/", "segment 'x y~^:z'", id="charset"
            ),
        ],
    )
    def test_assert_safe_branch_rejects_unsafe_names(
        self, sample_project: Project, branch: str, prefix: str, message: str
    ) -> None:
        """
        GIVEN a branch that is the default branch, outside a valid prefix, or
              not a valid git refname
        WHEN assert_safe_branch checks it
        THEN a DeliveryError explains which rule it broke
        """
        with pytest.raises(DeliveryError, match=re.escape(message)):
            assert_safe_branch(branch, sample_project, prefix)

    @pytest.mark.parametrize(
        ("branch", "prefix"),
        [
            ("engine/run-abc", "engine/"),
            (f"engine/trial-{RUN_ID}-h1.v2_x", "engine/"),
            ("bots/engine/run-x", "bots/engine/"),
        ],
    )
    def test_assert_safe_branch_accepts_prefixed_refnames(
        self, sample_project: Project, branch: str, prefix: str
    ) -> None:
        """
        GIVEN a valid refname under a valid engine prefix
        WHEN assert_safe_branch checks it
        THEN it returns normally
        """
        assert_safe_branch(branch, sample_project, prefix)

    def test_report_escapes_trial_controlled_text(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN a trial whose error text (copied into the verdict summary) tries
              to break out of the table with a heading, an image and a link
        WHEN deliver writes the report
        THEN the summary stays inside its one table row: no new heading, no
             raw HTML, no link syntax
        """
        payload = (
            "boom |\n\n## Approved by security team\r\n"
            "<img src=https://attacker.example/x?k=1>\n"
            "[merge now](https://attacker.example) `rm -rf` & \\| done"
        )
        scripts = {h1_cache.title: ScriptedOutcome(error=payload)}
        nodes = make_nodes(make_context([h1_cache], scripts))
        state = _advance(nodes, base_state, _before("deliver"))

        delivery = nodes["deliver"](state)["delivery"]

        assert isinstance(delivery, Delivery)
        report = delivery.report_markdown
        lines = report.splitlines()
        assert [line for line in lines if line.startswith("#")] == [lines[0]]
        assert "<img" not in report
        assert re.search(r"(?<!\\)\]\(", report) is None  # no unescaped link
        # GFM autolinks: no bare scheme, www. or e-mail survives in a cell
        rows = [line for line in lines if line.startswith("| ")]
        assert rows and all(re.search(r"(?<!\\):", row) is None for row in rows)
        assert re.search(r"(?i)www(?!\\)\.", report) is None
        (row,) = [line for line in lines if line.startswith(f"| {h1_cache.title} |")]
        assert row.endswith(
            "| reject | n/a | reject\\: trial failed\\: boom \\| ## Approved by "
            "security team &lt;img src=https\\://attacker.example/x?k=1&gt; "
            "\\[merge now\\](https\\://attacker.example) \\`rm -rf\\` &amp; "
            "\\\\\\| done |"
        )

    def test_report_neutralises_autolinks_and_unicode_line_breaks(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN a trial error carrying a www address, an e-mail address and
              Unicode line separators in front of a heading
        WHEN deliver writes the report
        THEN the address and the e-mail cannot autolink and the heading never
             starts a line, whatever splits lines (markdown, terminals, Python)
        """
        payload = (
            "see www.attacker.example or security@attacker.example"
            "\u2028## Approved\x85## by\v## security\f## team"
        )
        scripts = {h1_cache.title: ScriptedOutcome(error=payload)}
        nodes = make_nodes(make_context([h1_cache], scripts))
        state = _advance(nodes, base_state, _before("deliver"))

        delivery = nodes["deliver"](state)["delivery"]

        assert isinstance(delivery, Delivery)
        report = delivery.report_markdown
        assert [ln for ln in report.splitlines() if ln.startswith("#")] == [
            report.splitlines()[0]
        ]
        assert "www\\.attacker.example" in report
        assert "security\\@attacker.example" in report
        assert "Approved ## by ## security ## team" in report

    def test_report_heading_and_baseline_line_are_sanitised(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN a project name and a measurement unit that try to add a heading,
              raw HTML and a link outside the table
        WHEN deliver writes the report
        THEN the report has exactly one heading, no raw HTML and no link
        """
        project = base_state["project"].model_copy(
            update={"name": "bridge\n\n## Approved by security <img src=x>"}
        )
        unit_attack = "s\n\n[merge now](https://attacker.example)"
        baseline_script = ScriptedOutcome(
            samples={METRIC_WALL_TIME_S: (1.8,) * 5, VAL_LOSS: (0.5,) * 5},
            tests_passed=True,
        )

        class _UnitRunner(StubBaselineRunner):
            def measure(
                self,
                workloads: Sequence[Workload],
                *,
                run_id: str | None = None,
                commit: str | None = None,
            ) -> tuple[Measurement, ...]:
                return tuple(
                    m.model_copy(
                        update={
                            "stats": m.stats.model_copy(update={"unit": unit_attack})
                        }
                    )
                    for m in super().measure(workloads, run_id=run_id, commit=commit)
                )

        nodes = make_nodes(
            make_context([h1_cache], baseline_runner=_UnitRunner(baseline_script))
        )
        state = cast(EngineState, {**base_state, "project": project})
        state = _advance(nodes, state, _before("deliver"))

        delivery = nodes["deliver"](state)["delivery"]

        assert isinstance(delivery, Delivery)
        report = delivery.report_markdown
        lines = report.splitlines()
        assert [ln for ln in lines if ln.startswith("#")] == [lines[0]]
        assert "<img" not in report
        assert re.search(r"(?<!\\)\]\(", report) is None
        assert lines[0].startswith("# Engine run ")

    def test_report_cells_and_kept_titles_are_flattened_and_truncated(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
        design_scripts: dict[str, ScriptedOutcome],
    ) -> None:
        """
        GIVEN a kept hypothesis whose title spans lines and runs to 500 chars
        WHEN deliver writes the report
        THEN the title is one line in both the table and the kept list,
             cut to 200 characters ending with an ellipsis
        """
        title = "Cache\n# injected heading\n" + "x" * 500
        long_title = h1_cache.model_copy(update={"title": title})
        scripts = {long_title.id: design_scripts[h1_cache.title]}
        nodes = make_nodes(make_context([long_title], scripts))
        state = _advance(nodes, base_state, _before("deliver"))

        delivery = nodes["deliver"](state)["delivery"]

        assert isinstance(delivery, Delivery)
        flat = ("Cache # injected heading " + "x" * 500)[:199] + "…"
        assert len(flat) == 200
        report = delivery.report_markdown
        assert f"| {flat} | keep |" in report
        assert f"Kept: {flat}" in report
        assert not any(line.startswith("# injected") for line in report.splitlines())

    def test_report_shows_the_decided_outcomes(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
        h4_behaviour: Hypothesis,
    ) -> None:
        """
        GIVEN H4 approved at the gate next to the automatic keep H1
        WHEN deliver writes the report
        THEN H4's row reads keep, not needs_approval, and both are listed as kept
        """
        nodes = make_nodes(make_context([h1_cache, h4_behaviour]))
        state = _advance(nodes, base_state, _before("combine"))
        by_hypothesis = {v.hypothesis_id: v for v in state["verdicts"]}
        state["approval"] = ApprovalDecision(
            approved_verdict_ids=(by_hypothesis[h4_behaviour.id].id,), approver="pk"
        )
        state = _apply(state, nodes["combine"](state))

        delivery = nodes["deliver"](state)["delivery"]

        assert isinstance(delivery, Delivery)
        report = delivery.report_markdown
        assert f"| {h4_behaviour.title} | keep | +16.7% |" in report
        assert f"| {h4_behaviour.title} | needs_approval |" not in report
        assert f"Kept: {h1_cache.title}, {h4_behaviour.title}" in report

    def test_report_without_a_baseline_or_verdicts(
        self, make_context: ContextFactory, base_state: EngineState
    ) -> None:
        """
        GIVEN a state that never measured a baseline and has no verdicts
        WHEN deliver runs
        THEN the report says the baseline was not measured and nothing is kept
        """
        delta = make_nodes(make_context())["deliver"](base_state)

        delivery = delta["delivery"]
        assert isinstance(delivery, Delivery)
        assert delivery.kind is DeliveryKind.report_only
        report = delivery.report_markdown
        assert "Baseline: not measured" in report
        assert "| --- | --- | --- | --- |\n\nKept: nothing" in report


# ---------------------------------------------------------------------------
# decided_verdicts
# ---------------------------------------------------------------------------


class TestDecidedVerdicts:
    @staticmethod
    def _verdict(verdict_id: str, outcome: VerdictOutcome) -> Verdict:
        return Verdict(
            id=verdict_id,
            trial_id=f"trial-{verdict_id}",
            hypothesis_id=f"hypothesis-{verdict_id}",
            outcome=outcome,
            change_class=ChangeClass.behaviour,
            summary=f"{outcome}: judged",
        )

    def test_without_a_decision_the_verdicts_are_unchanged(self) -> None:
        """
        GIVEN verdicts and no approval decision
        WHEN decided_verdicts applies it
        THEN the same verdicts come back in order
        """
        verdicts = [
            self._verdict("a", VerdictOutcome.keep),
            self._verdict("b", VerdictOutcome.needs_approval),
        ]

        assert decided_verdicts(verdicts, None) == verdicts

    def test_the_decision_rewrites_only_needs_approval_verdicts(self) -> None:
        """
        GIVEN a keep, an inconclusive and three needs_approval verdicts, and a
              decision approving one, rejecting one and naming the keep and
              inconclusive ones too
        WHEN decided_verdicts applies it
        THEN approved -> keep with approver and note, rejected -> reject with
             the note, undecided and non-pending verdicts untouched, order kept
        """
        keep = self._verdict("keep", VerdictOutcome.keep)
        unsure = self._verdict("unsure", VerdictOutcome.inconclusive)
        yes = self._verdict("yes", VerdictOutcome.needs_approval)
        no = self._verdict("no", VerdictOutcome.needs_approval)
        later = self._verdict("later", VerdictOutcome.needs_approval)
        decision = ApprovalDecision(
            approved_verdict_ids=("yes", "keep"),
            rejected_verdict_ids=("no", "unsure"),
            approver="pk",
            note="reviewed",
        )

        decided = decided_verdicts([keep, unsure, yes, no, later], decision)

        assert [v.id for v in decided] == ["keep", "unsure", "yes", "no", "later"]
        assert decided[0] is keep and decided[1] is unsure and decided[4] is later
        assert decided[2].outcome is VerdictOutcome.keep
        assert (decided[2].approved_by, decided[2].approval_note) == ("pk", "reviewed")
        assert decided[3].outcome is VerdictOutcome.reject
        assert (decided[3].approved_by, decided[3].approval_note) == (None, "reviewed")
        assert yes.summary == "needs_approval: judged"
        assert decided[2].summary == "approved by pk: judged"
        assert decided[3].summary == "rejected by pk: judged"


# ---------------------------------------------------------------------------
# learn
# ---------------------------------------------------------------------------


class TestLearn:
    def test_saves_one_lesson_per_verdict_with_hotspot_context(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_project: Project,
        sample_workload: Workload,
        h1_cache: Hypothesis,
        h3_noise: Hypothesis,
    ) -> None:
        """
        GIVEN two verdicts and hotspots tagged hot_loop and frozen_encoder
        WHEN learn runs
        THEN one lesson per verdict is saved, tagged with the sorted unique tags
        """
        hotspots = (
            _hotspot(sample_project, sample_workload, "hot_loop", "frozen_encoder"),
            _hotspot(sample_project, sample_workload, "hot_loop"),
        )
        ctx = make_context([h1_cache, h3_noise], hotspots=hotspots)
        nodes = make_nodes(ctx)
        state = _advance(nodes, base_state, _before("learn"))

        delta = nodes["learn"](state)

        lessons = _items(delta, "lessons", Lesson)
        assert [lesson.outcome for lesson in lessons] == [
            VerdictOutcome.keep,
            VerdictOutcome.inconclusive,
        ]
        assert all(lesson.project_id == sample_project.id for lesson in lessons)
        assert all(
            lesson.context == ("frozen_encoder", "hot_loop") for lesson in lessons
        )
        assert ctx.repository.list_lessons(sample_project.id) == tuple(lessons)
        assert _only_event(delta).data == {"lessons": 2}

    def test_approval_decisions_teach(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h4_behaviour: Hypothesis,
    ) -> None:
        """
        GIVEN needs_approval verdicts that were approved, rejected or left undecided
        WHEN learn runs
        THEN the lessons record keep, reject and needs_approval respectively
        """
        nodes = make_nodes(make_context([h4_behaviour]))
        state = _advance(nodes, base_state, _before("combine"))
        (verdict,) = state["verdicts"]
        rejected = verdict.model_copy(update={"id": "rejected-one"})
        undecided = verdict.model_copy(update={"id": "undecided-one"})
        state["verdicts"] = [verdict, rejected, undecided]
        state["approval"] = ApprovalDecision(
            approved_verdict_ids=(verdict.id,),
            rejected_verdict_ids=(rejected.id,),
            approver="praveen",
        )

        lessons = _items(nodes["learn"](state), "lessons", Lesson)

        assert [lesson.outcome for lesson in lessons] == [
            VerdictOutcome.keep,
            VerdictOutcome.reject,
            VerdictOutcome.needs_approval,
        ]
        assert lessons[0].text.endswith("keep (+16.7%)")

    def test_approval_leaves_other_verdicts_untouched(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
        h4_behaviour: Hypothesis,
    ) -> None:
        """
        GIVEN a keep verdict (H1) next to an approved needs_approval one (H4)
        WHEN learn runs
        THEN H1's lesson is unchanged and only H4's records the approver
        """
        nodes = make_nodes(make_context([h1_cache, h4_behaviour]))
        state = _advance(nodes, base_state, _before("combine"))
        by_hypothesis = {v.hypothesis_id: v for v in state["verdicts"]}
        state["approval"] = ApprovalDecision(
            approved_verdict_ids=(by_hypothesis[h4_behaviour.id].id,), approver="pk"
        )

        lessons = _items(nodes["learn"](state), "lessons", Lesson)

        by_id = {lesson.hypothesis_id: lesson for lesson in lessons}
        assert by_id[h1_cache.id].outcome is VerdictOutcome.keep
        assert by_id[h1_cache.id].verdict_id == by_hypothesis[h1_cache.id].id
        assert by_id[h4_behaviour.id].outcome is VerdictOutcome.keep
        assert len(lessons) == 2

    def test_warns_about_verdicts_with_unknown_hypotheses(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN a verdict whose hypothesis is missing from the state
        WHEN learn runs
        THEN no lesson is derived and a warning event names the hypothesis
        """
        nodes = make_nodes(make_context([h1_cache]))
        state = _advance(nodes, base_state, _before("learn"))
        state["hypotheses"] = []

        delta = nodes["learn"](state)

        assert delta["lessons"] == []
        info, warning = _events(delta)
        assert info.level is EventLevel.info
        assert warning.level is EventLevel.warning
        assert h1_cache.id in warning.message


# ---------------------------------------------------------------------------
# watch
# ---------------------------------------------------------------------------


class TestWatch:
    def test_marks_the_run_done(
        self, make_context: ContextFactory, base_state: EngineState
    ) -> None:
        """
        GIVEN any state
        WHEN watch runs
        THEN the phase is done and the event announces the watch stub
        """
        delta = make_nodes(make_context())["watch"](base_state)

        assert delta["phase"] is RunPhase.done
        event = _only_event(delta)
        assert event.phase is RunPhase.watch
        assert event.message == "watching for new papers and code changes (stub)"


# ---------------------------------------------------------------------------
# repository is the only side channel
# ---------------------------------------------------------------------------


def test_nodes_write_nothing_but_trials_verdicts_and_lessons_to_the_repository(
    make_context: ContextFactory, base_state: EngineState, h1_cache: Hypothesis
) -> None:
    """
    GIVEN a full linear pass with one kept hypothesis
    WHEN the repository is inspected afterwards
    THEN it holds one trial, one verdict and one lesson and no run state
    """
    repository = InMemoryRepository()
    nodes = make_nodes(make_context([h1_cache], repository=repository))

    _advance(nodes, base_state, LINEAR_PATH)

    assert len(repository.list_trials(RUN_ID)) == 1
    assert len(repository.list_verdicts(RUN_ID)) == 1
    assert len(repository.list_lessons()) == 1
    assert repository.get_run(RUN_ID) is None


# ---------------------------------------------------------------------------
# Step 2 (U10): the seams behind preflight, understand, profile, the running
# budget, the violation merge, the combine re-test and the publisher
# ---------------------------------------------------------------------------

SHA = "a" * 40
TIP = "b" * 40
SLOW = (1.80, 1.75, 1.85, 1.80, 1.80)
FAST = (1.05, 1.02, 1.08, 1.05, 1.05)


def _coded(delta: NodeDelta, code: str) -> list[EngineEvent]:
    return [event for event in _events(delta) if event.data.get("code") == code]


def _preflight_report(
    workloads: Sequence[Workload],
    *,
    dirty: Sequence[str] = (),
    network: IsolationMode = "required",
    fs: IsolationMode = "required",
    test_command: tuple[str, ...] | None = None,
    extra: Sequence[str] = (),
    head: str = SHA,
) -> PreflightReport:
    return PreflightReport(
        head_commit=head,
        dirty_entries=tuple(dirty),
        git_version=(2, 43, 0),
        network=network,
        fs=fs,
        workloads=tuple(workloads),
        test_command=test_command,
        extra_protected=tuple(extra),
    )


def _efficiency(
    project: Project, hypothesis_id: str, title: str, expected_gain: float = 0.4
) -> Hypothesis:
    return Hypothesis(
        id=hypothesis_id,
        project_id=project.id,
        source=HypothesisSource.playbook,
        title=title,
        rationale=f"{title}: scripted for the combine tests",
        change_class=ChangeClass.efficiency,
        expected_gain=expected_gain,
        provability=0.9,
        risk=0.1,
    )


DESIGN_SCRIPTS_H1 = ScriptedOutcome(
    touched_paths=("src/bridge/encoder.py",),
    samples={METRIC_WALL_TIME_S: FAST, VAL_LOSS: (0.5,) * 5},
    tests_passed=True,
    cost_usd=0.12,
    tokens_used=3400,
)


def _winning(wall: Sequence[float]) -> ScriptedOutcome:
    return replace(
        DESIGN_SCRIPTS_H1,
        samples={METRIC_WALL_TIME_S: tuple(wall), VAL_LOSS: (0.5,) * 5},
    )


def _rows(
    workload_id: str,
    wall: Sequence[float],
    *,
    val_loss: Sequence[float] = (0.5,) * 5,
    tests: float | None = 1.0,
) -> tuple[Measurement, ...]:
    rows = [
        _measurement(workload_id, METRIC_WALL_TIME_S, wall),
        _measurement(workload_id, VAL_LOSS, val_loss, unit=""),
    ]
    if tests is not None:
        rows.append(
            _measurement(workload_id, METRIC_TESTS_PASSED, (tests,), unit="bool")
        )
    return tuple(rows)


def _measured(
    workload_id: str,
    applied: Sequence[str],
    *,
    tip: str = TIP,
    skipped: Sequence[CombineSkip] = (),
    baseline: tuple[Measurement, ...] | None = None,
    combined: tuple[Measurement, ...] | None = None,
) -> CombineMeasured:
    return CombineMeasured(
        tip_commit=tip,
        applied=tuple(applied),
        skipped=tuple(skipped),
        baseline=_rows(workload_id, SLOW, tests=None) if baseline is None else baseline,
        combined=_rows(workload_id, FAST) if combined is None else combined,
    )


def _cv(samples: Sequence[float]) -> float:
    stats = RunStats.from_samples(samples, unit="s")
    return stats.stdev / stats.mean


def _committed(state: EngineState) -> EngineState:
    """``state`` pinned at SHA, every trial committed (as the real runner does)."""
    trials = [
        trial.model_copy(update={"commit": f"{index + 1:040x}"})
        for index, trial in enumerate(state["trials"])
    ]
    return cast(EngineState, {**state, "trials": trials, "base_commit": SHA})


def _trial_of(state: EngineState, hypothesis: Hypothesis) -> Trial:
    return next(t for t in state["trials"] if t.hypothesis_id == hypothesis.id)


def _verdict_of(state: EngineState, hypothesis: Hypothesis) -> Verdict:
    return next(v for v in state["verdicts"] if v.hypothesis_id == hypothesis.id)


class _FixedBaselineRunner:
    """A baseline runner that returns the given rows whatever it is asked."""

    def __init__(self, rows: Sequence[Measurement]) -> None:
        self._rows = tuple(rows)

    def measure(
        self, workloads: Sequence[Workload], *, run_id: str, commit: str | None
    ) -> tuple[Measurement, ...]:
        return self._rows


class _ChargingUnderstander:
    """Charges the budget it is given, then returns or raises its outcome."""

    def __init__(
        self, usd: float, tokens: int, outcome: UnderstandResult | Exception
    ) -> None:
        self._usd, self._tokens, self._outcome = usd, tokens, outcome

    def understand(
        self,
        project: Project,
        workloads: Sequence[Workload],
        *,
        commit: str,
        budget: Budget,
    ) -> UnderstandResult:
        budget.record(self._usd, self._tokens)
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


class TestStep2Context:
    def test_seams_default_to_none_and_the_trial_floor_to_zero(
        self, make_context: ContextFactory
    ) -> None:
        """
        GIVEN a node context built without the Step 2 seams
        WHEN its fields are read
        THEN every seam is None (Step 1 behaviour) and min_trial_budget_usd is 0
        """
        ctx = make_context()

        assert (
            ctx.preflight,
            ctx.understander,
            ctx.profiler,
            ctx.combiner,
            ctx.publisher,
        ) == (None, None, None, None, None)
        assert ctx.min_trial_budget_usd == 0.0

    @pytest.mark.parametrize("value", [-0.01, math.nan, math.inf])
    def test_min_trial_budget_must_be_finite_and_not_negative(
        self, make_context: ContextFactory, value: float
    ) -> None:
        """
        GIVEN a negative, NaN or infinite min_trial_budget_usd
        WHEN a node context is built
        THEN a ValueError names the knob (NaN would let every trial start)
        """
        with pytest.raises(ValueError, match="min_trial_budget_usd"):
            make_context(min_trial_budget_usd=value)


class TestConnectWithPreflight:
    def test_pins_the_commit_and_the_resolved_inputs(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_project: Project,
        sample_workload: Workload,
        sample_guardrails: tuple[Guardrail, ...],
    ) -> None:
        """
        GIVEN a preflight that resolves the workload's python, a test command
              and a repo-relative harness path, on a clean tree
        WHEN connect runs
        THEN the preflight sees the project, workloads and guardrails; the
             state pins the head commit and takes the resolved workloads, test
             command and extra protected paths; one info isolation event follows
        """
        resolved = sample_workload.model_copy(
            update={"command": ("/usr/bin/python3", "train.py", "--steps", "20")}
        )
        command = ("/usr/bin/python3", "-m", "pytest")
        preflight = FakePreflight(
            _preflight_report([resolved], test_command=command, extra=("run.sh",))
        )

        delta = make_nodes(make_context(preflight=preflight))["connect"](base_state)

        assert preflight.calls == [
            PreflightCall(sample_project, (sample_workload,), sample_guardrails)
        ]
        assert set(delta) == {
            "phase",
            "project",
            "workloads",
            "base_commit",
            "extra_protected",
            "events",
        }
        assert delta["base_commit"] == SHA
        assert delta["workloads"] == [resolved]
        assert delta["extra_protected"] == ["run.sh"]
        project = delta["project"]
        assert isinstance(project, Project)
        assert project.test_command == command
        assert project.model_copy(update={"test_command": None}) == sample_project
        connected, isolation = _events(delta)
        assert connected.message == f"connected bridge at {SHA}"
        assert connected.data == {
            "workloads": 1,
            "base_commit": SHA,
            "git_version": "2.43.0",
        }
        assert isolation.level is EventLevel.info
        assert isolation.data == {
            "code": "isolation",
            "network": "required",
            "fs": "required",
        }

    def test_warns_that_uncommitted_changes_are_ignored(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_workload: Workload,
    ) -> None:
        """
        GIVEN a preflight that saw two uncommitted entries
        WHEN connect runs
        THEN a dirty_tree_ignored warning gives the count and the measured sha
        """
        preflight = FakePreflight(
            _preflight_report([sample_workload], dirty=(" M a.py", "?? b.txt"))
        )

        delta = make_nodes(make_context(preflight=preflight))["connect"](base_state)

        (dirty,) = _coded(delta, "dirty_tree_ignored")
        assert dirty.level is EventLevel.warning
        assert dirty.message.endswith(
            f"2 uncommitted changes ignored; run measures {SHA}"
        )
        assert dirty.data == {
            "code": "dirty_tree_ignored",
            "dirty_entries": 2,
            "base_commit": SHA,
        }

    @pytest.mark.parametrize(
        ("network", "fs", "level"),
        [
            ("required", "required", EventLevel.info),
            ("best_effort", "required", EventLevel.warning),
            ("required", "off", EventLevel.warning),
            ("off", "best_effort", EventLevel.warning),
        ],
    )
    def test_isolation_modes_warn_unless_both_are_required(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_workload: Workload,
        network: IsolationMode,
        fs: IsolationMode,
        level: EventLevel,
    ) -> None:
        """
        GIVEN the isolation modes the preflight reports
        WHEN connect runs
        THEN the isolation event names both, at warning level unless both
             are required
        """
        preflight = FakePreflight(
            _preflight_report([sample_workload], network=network, fs=fs)
        )

        delta = make_nodes(make_context(preflight=preflight))["connect"](base_state)

        (isolation,) = _coded(delta, "isolation")
        assert isolation.level is level
        assert f"network {network}, filesystem {fs}" in isolation.message

    def test_warns_once_per_workload_whose_inputs_are_ignored(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_project: Project,
        sample_workload: Workload,
    ) -> None:
        """
        GIVEN two workloads, only the second with inputs
        WHEN connect runs
        THEN exactly one workload_inputs_ignored warning names that workload
             and counts its inputs (Step 2 never passes Workload.inputs)
        """
        with_inputs = Workload(
            project_id=sample_project.id,
            name="eval",
            command=("python", "eval.py"),
            inputs={"split": "val", "limit": 100},
        )
        workloads = [sample_workload, with_inputs]
        state = cast(EngineState, {**base_state, "workloads": workloads})
        preflight = FakePreflight(_preflight_report(workloads))

        delta = make_nodes(make_context(preflight=preflight))["connect"](state)

        (ignored,) = _coded(delta, "workload_inputs_ignored")
        assert ignored.level is EventLevel.warning
        assert "eval" in ignored.message
        assert ignored.data == {
            "code": "workload_inputs_ignored",
            "workload_id": with_inputs.id,
            "inputs": 2,
        }

    def test_a_preflight_error_stops_the_run(
        self, make_context: ContextFactory, base_state: EngineState
    ) -> None:
        """
        GIVEN a preflight that refuses the repository
        WHEN connect runs
        THEN its PreflightError (an EngineError) propagates
        """
        preflight = FakePreflight(error=PreflightError("git 2.30 is older than 2.38"))

        with pytest.raises(PreflightError, match="older than 2.38"):
            make_nodes(make_context(preflight=preflight))["connect"](base_state)
        assert issubclass(PreflightError, EngineError)

    @pytest.mark.parametrize(
        "head", ["", "HEAD", "--upload-pack=evil", "A" * 40, "a" * 39, "a" * 41]
    )
    def test_refuses_a_head_that_is_not_a_full_commit_id(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_workload: Workload,
        head: str,
    ) -> None:
        """
        GIVEN a preflight report whose head commit is not 40 or 64 lowercase hex
        WHEN connect runs
        THEN an EngineError refuses it: the sha later reaches git argv
        """
        preflight = FakePreflight(_preflight_report([sample_workload], head=head))

        with pytest.raises(EngineError, match="commit"):
            make_nodes(make_context(preflight=preflight))["connect"](base_state)

    def test_accepts_a_sha256_head(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_workload: Workload,
    ) -> None:
        """
        GIVEN a SHA-256 repository (64 hex digit commit ids)
        WHEN connect runs
        THEN the commit is pinned
        """
        head = "c" * 64
        preflight = FakePreflight(_preflight_report([sample_workload], head=head))

        delta = make_nodes(make_context(preflight=preflight))["connect"](base_state)

        assert delta["base_commit"] == head

    def test_refuses_resolved_workloads_that_are_not_the_runs(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_project: Project,
    ) -> None:
        """
        GIVEN a preflight report that returns a different workload
        WHEN connect runs
        THEN an EngineError says the resolved workloads do not match
        """
        stranger = Workload(project_id=sample_project.id, name="x", command=("x",))
        preflight = FakePreflight(_preflight_report([stranger]))

        with pytest.raises(EngineError, match="workloads"):
            make_nodes(make_context(preflight=preflight))["connect"](base_state)

    def test_each_preflight_note_is_a_warning_event_in_order(
        self, make_context: ContextFactory, base_state: EngineState
    ) -> None:
        """
        GIVEN a preflight that reports two notes (accepted risks it found)
        WHEN connect runs
        THEN each note is one preflight_note warning, in the report's order,
             after the connected event and the isolation event
        """
        notes = (
            "merge=union in .gitattributes: a combine conflict may be hidden",
            "workload 'train' is not parsed for its Python syntax level",
        )
        preflight = FakePreflight(notes=notes)

        delta = make_nodes(make_context(preflight=preflight))["connect"](base_state)

        found = _coded(delta, "preflight_note")
        assert [event.data for event in found] == [
            {"code": "preflight_note", "note": note} for note in notes
        ]
        assert all(event.level is EventLevel.warning for event in found)
        assert [event.message for event in found] == [
            f"preflight_note: {note}" for note in notes
        ]
        codes = [event.data.get("code") for event in _events(delta)]
        assert codes.index("isolation") < codes.index("preflight_note")

    def test_the_engine_python_version_is_an_info_event(
        self, make_context: ContextFactory, base_state: EngineState
    ) -> None:
        """
        GIVEN a preflight that recorded the engine's interpreter version
        WHEN connect runs
        THEN one engine_python info event carries it as text
        """
        preflight = FakePreflight(python_version=(3, 11, 9))

        delta = make_nodes(make_context(preflight=preflight))["connect"](base_state)

        (python,) = _coded(delta, "engine_python")
        assert python.level is EventLevel.info
        assert python.message == "engine_python: the engine runs Python 3.11.9"
        assert python.data == {"code": "engine_python", "python_version": "3.11.9"}

    def test_no_note_or_version_events_when_the_report_has_none(
        self, make_context: ContextFactory, base_state: EngineState
    ) -> None:
        """
        GIVEN a preflight report with no notes and no python version
        WHEN connect runs
        THEN neither preflight_note nor engine_python is emitted
        """
        delta = make_nodes(make_context(preflight=FakePreflight()))["connect"](
            base_state
        )

        assert _coded(delta, "preflight_note") == []
        assert _coded(delta, "engine_python") == []


class TestUnderstandWithUnderstander:
    @pytest.fixture
    def pinned(self, base_state: EngineState) -> EngineState:
        return cast(
            EngineState,
            {
                **base_state,
                "base_commit": SHA,
                "max_cost_usd": 2.0,
                "cost_usd": 0.5,
                "tokens_used": 100,
            },
        )

    def test_reads_the_project_at_the_base_within_the_run_budget(
        self,
        make_context: ContextFactory,
        pinned: EngineState,
        sample_project: Project,
        sample_workload: Workload,
    ) -> None:
        """
        GIVEN a 2.00 USD cap with 0.50 spent and an understander costing 0.03
        WHEN understand runs
        THEN it reads the project at the base commit with Budget(2.0, 0.5),
             the state gets the understanding, and cost and tokens add up
        """
        understanding = ProjectUnderstanding(
            language="python", summary="dedupe helpers", served_by_model="m"
        )
        understander = FakeUnderstander(
            UnderstandResult(
                understanding, notes=("dropped x.py",), cost_usd=0.03, tokens_used=1200
            )
        )

        delta = make_nodes(make_context(understander=understander))["understand"](
            pinned
        )

        assert understander.calls == [
            UnderstandCall(sample_project, (sample_workload,), SHA, 2.0, 0.5)
        ]
        assert set(delta) == {
            "phase",
            "understanding",
            "cost_usd",
            "tokens_used",
            "events",
        }
        assert delta["understanding"] == understanding
        assert delta["cost_usd"] == pytest.approx(0.53)
        assert delta["tokens_used"] == 1300
        understood, note = _events(delta)
        assert understood.level is EventLevel.info
        assert "python" in understood.message
        assert note.data["code"] == "understand_note"
        assert "dropped x.py" in note.message

    def test_a_soft_failure_result_warns(
        self, make_context: ContextFactory, pinned: EngineState
    ) -> None:
        """
        GIVEN an understander that returns no understanding
        WHEN understand runs
        THEN the state's understanding is None and a warning says so
        """
        understander = FakeUnderstander(UnderstandResult(None, cost_usd=0.01))

        delta = make_nodes(make_context(understander=understander))["understand"](
            pinned
        )

        assert delta["understanding"] is None
        assert delta["cost_usd"] == pytest.approx(0.51)
        (warning,) = _events(delta)
        assert warning.level is EventLevel.warning
        assert warning.data["code"] == "understand_unavailable"

    @pytest.mark.parametrize(
        "error",
        [
            BudgetExceeded("cap reached"),
            LLMConfigError("401 from the API"),
            RepoTamperedError("refs changed"),
        ],
        ids=["budget", "config", "tampered"],
    )
    def test_engine_errors_stop_the_run(
        self, make_context: ContextFactory, pinned: EngineState, error: EngineError
    ) -> None:
        """
        GIVEN an understander that raises BudgetExceeded, LLMConfigError or
              any other EngineError
        WHEN understand runs
        THEN the error propagates: an EngineError means the run cannot go on
        """
        understander = FakeUnderstander(error=error)

        with pytest.raises(type(error)):
            make_nodes(make_context(understander=understander))["understand"](pinned)

    @pytest.mark.parametrize(
        "error",
        [
            LLMUnavailable("529 overloaded"),
            LLMRequestError("400 bad request"),
            ValueError("reply did not match the schema"),
            RuntimeError("bug"),
        ],
        ids=["unavailable", "request", "schema", "other"],
    )
    def test_any_other_failure_leaves_no_understanding_and_warns(
        self, make_context: ContextFactory, pinned: EngineState, error: Exception
    ) -> None:
        """
        GIVEN an understander that raises anything else
        WHEN understand runs
        THEN the run goes on without an understanding and a warning names
             the error type; nothing was charged
        """
        understander = FakeUnderstander(error=error)

        delta = make_nodes(make_context(understander=understander))["understand"](
            pinned
        )

        assert delta["understanding"] is None
        assert delta["cost_usd"] == pytest.approx(0.5)
        assert delta["tokens_used"] == 100
        (warning,) = _events(delta)
        assert warning.level is EventLevel.warning
        assert warning.data["code"] == "understand_failed"
        assert type(error).__name__ in warning.message

    def test_money_charged_before_a_failure_still_counts(
        self, make_context: ContextFactory, pinned: EngineState
    ) -> None:
        """
        GIVEN an understander that charges 0.04 USD to the budget, then times out
        WHEN understand runs
        THEN the 0.04 USD and its tokens are on the run's total anyway
        """
        understander = _ChargingUnderstander(0.04, 900, LLMUnavailable("timeout"))

        delta = make_nodes(make_context(understander=understander))["understand"](
            pinned
        )

        assert delta["understanding"] is None
        assert delta["cost_usd"] == pytest.approx(0.54)
        assert delta["tokens_used"] == 1000

    def test_a_charge_reported_twice_is_counted_once(
        self, make_context: ContextFactory, pinned: EngineState
    ) -> None:
        """
        GIVEN an understander that charges 0.02 USD to the budget and also
              reports the same 0.02 USD in its result
        WHEN understand runs
        THEN the run total grows by 0.02 USD, not 0.04
        """
        result = UnderstandResult(None, cost_usd=0.02, tokens_used=500)
        understander = _ChargingUnderstander(0.02, 500, result)

        delta = make_nodes(make_context(understander=understander))["understand"](
            pinned
        )

        assert delta["cost_usd"] == pytest.approx(0.52)
        assert delta["tokens_used"] == 600

    def test_needs_a_pinned_commit(
        self, make_context: ContextFactory, base_state: EngineState
    ) -> None:
        """
        GIVEN an understander but no pinned base commit (no preflight ran)
        WHEN understand runs
        THEN an EngineError says the commit is missing
        """
        understander = FakeUnderstander(UnderstandResult(None))

        with pytest.raises(EngineError, match="base commit"):
            make_nodes(make_context(understander=understander))["understand"](
                base_state
            )
        assert understander.calls == []


class TestBaselineStep2:
    def test_records_the_pinned_commit_on_the_baseline(
        self, make_context: ContextFactory, base_state: EngineState
    ) -> None:
        """
        GIVEN a state pinned at SHA
        WHEN baseline runs
        THEN the baseline records the commit it measured
        """
        state = cast(EngineState, {**base_state, "base_commit": SHA})

        baseline = make_nodes(make_context())["baseline"](state)["baseline"]

        assert isinstance(baseline, Baseline)
        assert baseline.commit == SHA

    def test_missing_output_fingerprints_fail_closed_under_equivalence(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_project: Project,
    ) -> None:
        """
        GIVEN an output_equivalence guardrail and a baseline whose runs did not
              agree on one output (no fingerprint)
        WHEN baseline runs
        THEN an EngineError asks for a seed or an output_file before any
             money is spent on trials
        """
        equivalence = Guardrail(
            project_id=sample_project.id,
            kind=GuardrailKind.output_equivalence,
            description="outputs must not change",
        )
        state = cast(
            EngineState,
            {**base_state, "guardrails": [*base_state["guardrails"], equivalence]},
        )
        script = ScriptedOutcome(
            samples={METRIC_WALL_TIME_S: SLOW, VAL_LOSS: (0.5,) * 5}, tests_passed=True
        )
        ctx = make_context(baseline_runner=StubBaselineRunner(script))

        with pytest.raises(EngineError, match="nondeterministic or missing output"):
            make_nodes(ctx)["baseline"](state)

    def test_agreed_fingerprints_pass_under_equivalence(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_project: Project,
    ) -> None:
        """
        GIVEN an output_equivalence guardrail and a baseline whose runs agreed
              on one output fingerprint
        WHEN baseline runs
        THEN the baseline is measured
        """
        equivalence = Guardrail(
            project_id=sample_project.id,
            kind=GuardrailKind.output_equivalence,
            description="outputs must not change",
        )
        state = cast(
            EngineState,
            {**base_state, "guardrails": [*base_state["guardrails"], equivalence]},
        )

        delta = make_nodes(make_context())["baseline"](state)

        assert isinstance(delta["baseline"], Baseline)

    def test_missing_fingerprints_are_fine_without_equivalence(
        self, make_context: ContextFactory, base_state: EngineState
    ) -> None:
        """
        GIVEN no output_equivalence guardrail and no fingerprints
        WHEN baseline runs
        THEN the baseline is measured
        """
        script = ScriptedOutcome(
            samples={METRIC_WALL_TIME_S: SLOW, VAL_LOSS: (0.5,) * 5}, tests_passed=True
        )
        ctx = make_context(baseline_runner=StubBaselineRunner(script))

        assert isinstance(make_nodes(ctx)["baseline"](base_state)["baseline"], Baseline)

    def test_a_failing_test_suite_fails_closed_under_tests_pass(
        self, make_context: ContextFactory, base_state: EngineState
    ) -> None:
        """
        GIVEN a tests_pass guardrail and a baseline whose test suite fails
        WHEN baseline runs
        THEN an EngineError says the suite already fails at the base
        """
        script = ScriptedOutcome(
            samples={METRIC_WALL_TIME_S: SLOW, VAL_LOSS: (0.5,) * 5},
            tests_passed=False,
        )
        ctx = make_context(baseline_runner=StubBaselineRunner(script))

        with pytest.raises(EngineError, match="test suite"):
            make_nodes(ctx)["baseline"](base_state)

    def test_a_failing_suite_is_fine_without_tests_pass(
        self, make_context: ContextFactory, base_state: EngineState
    ) -> None:
        """
        GIVEN no tests_pass guardrail and a failing tests_passed row
        WHEN baseline runs
        THEN the baseline is measured (nobody asked for passing tests)
        """
        state = cast(
            EngineState,
            {
                **base_state,
                "guardrails": [
                    g
                    for g in base_state["guardrails"]
                    if g.kind is not GuardrailKind.tests_pass
                ],
            },
        )
        script = ScriptedOutcome(
            samples={METRIC_WALL_TIME_S: SLOW, VAL_LOSS: (0.5,) * 5},
            tests_passed=False,
        )
        ctx = make_context(baseline_runner=StubBaselineRunner(script))

        assert isinstance(make_nodes(ctx)["baseline"](state)["baseline"], Baseline)

    def test_a_quiet_host_gets_an_info_noisy_host_with_its_floor(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_workload: Workload,
    ) -> None:
        """
        GIVEN the design baseline (CV 1.96 %, mean 1.80 s)
        WHEN baseline runs
        THEN the baseline event comes first, then one info-level noisy_host
             event for the workload with the smallest provable gain
             max(2 x CV, 2 %) = 3.93 %, which the baseline event also reports
        """
        delta = make_nodes(make_context())["baseline"](base_state)

        summary, note = _events(delta)
        cv = _cv(SLOW)
        assert "code" not in summary.data
        assert summary.data["smallest_provable_gain"] == pytest.approx(2 * cv)
        assert note.data["code"] == "noisy_host"
        assert note.phase is RunPhase.baseline
        assert note.level is EventLevel.info
        assert note.message.startswith("noisy_host: workload train-step: CV 2.0%")
        assert "start-up" not in note.message
        assert note.data["workload_id"] == sample_workload.id
        assert note.data["cv"] == pytest.approx(cv)
        assert note.data["smallest_provable_gain"] == pytest.approx(2 * cv)

    def test_a_noisy_workload_gets_a_warning_with_its_floor(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_workload: Workload,
    ) -> None:
        """
        GIVEN a baseline whose wall time varies by about 25 %
        WHEN baseline runs
        THEN a noisy_host warning names the workload with its CV and the
             smallest provable gain 2 x CV
        """
        noisy = (1.0, 1.3, 0.8, 1.2, 0.7)
        script = ScriptedOutcome(
            samples={METRIC_WALL_TIME_S: noisy, VAL_LOSS: (0.5,) * 5}, tests_passed=True
        )
        ctx = make_context(baseline_runner=StubBaselineRunner(script))

        delta = make_nodes(ctx)["baseline"](base_state)

        (warning,) = _coded(delta, "noisy_host")
        cv = _cv(noisy)
        assert warning.level is EventLevel.warning
        assert sample_workload.name in warning.message
        assert warning.data["workload_id"] == sample_workload.id
        assert warning.data["cv"] == pytest.approx(cv)
        assert warning.data["smallest_provable_gain"] == pytest.approx(2 * cv)

    def test_a_short_workload_gets_a_warning_even_when_steady(
        self, make_context: ContextFactory, base_state: EngineState
    ) -> None:
        """
        GIVEN a steady baseline whose mean wall time is 0.2 s
        WHEN baseline runs
        THEN a noisy_host warning says runs under 0.5 s are start-up dominated
        """
        script = ScriptedOutcome(
            samples={METRIC_WALL_TIME_S: (0.2,) * 5, VAL_LOSS: (0.5,) * 5},
            tests_passed=True,
        )
        ctx = make_context(baseline_runner=StubBaselineRunner(script))

        (warning,) = _coded(make_nodes(ctx)["baseline"](base_state), "noisy_host")

        assert warning.level is EventLevel.warning
        assert "0.5 s" in warning.message
        assert warning.data["smallest_provable_gain"] == pytest.approx(0.02)

    def test_a_zero_mean_cannot_prove_any_relative_gain(
        self, make_context: ContextFactory, base_state: EngineState
    ) -> None:
        """
        GIVEN a primary metric whose baseline mean is 0
        WHEN baseline runs
        THEN a noisy_host warning says no relative gain is provable (no NaN)
        """
        script = ScriptedOutcome(
            samples={METRIC_WALL_TIME_S: (0.0,) * 5, VAL_LOSS: (0.5,) * 5},
            tests_passed=True,
        )
        ctx = make_context(baseline_runner=StubBaselineRunner(script))

        delta = make_nodes(ctx)["baseline"](base_state)

        (warning,) = _coded(delta, "noisy_host")
        assert warning.level is EventLevel.warning
        assert warning.data["smallest_provable_gain"] is None
        assert warning.data["cv"] is None
        (summary,) = [e for e in _events(delta) if "code" not in e.data]
        assert summary.data["smallest_provable_gain"] is None

    def test_each_of_two_workloads_gets_a_noisy_host_at_its_own_level(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_project: Project,
        sample_workload: Workload,
    ) -> None:
        """
        GIVEN two workloads, the second noisy
        WHEN baseline runs
        THEN one noisy_host event per workload, in workload order: info for
             the quiet first, warning for the noisy second; the baseline
             event reports the worse floor
        """
        other = Workload(project_id=sample_project.id, name="eval", command=("x",))
        noisy = (1.0, 1.3, 0.8, 1.2, 0.7)
        rows = [
            *_rows(sample_workload.id, SLOW),
            *_rows(other.id, noisy),
        ]
        state = cast(EngineState, {**base_state, "workloads": [sample_workload, other]})
        ctx = make_context(baseline_runner=_FixedBaselineRunner(rows))

        delta = make_nodes(ctx)["baseline"](state)

        quiet, loud = _coded(delta, "noisy_host")
        assert (quiet.data["workload_id"], quiet.level) == (
            sample_workload.id,
            EventLevel.info,
        )
        assert (loud.data["workload_id"], loud.level) == (other.id, EventLevel.warning)
        assert quiet.data["smallest_provable_gain"] == pytest.approx(2 * _cv(SLOW))
        (summary,) = [e for e in _events(delta) if "code" not in e.data]
        assert summary.data["smallest_provable_gain"] == pytest.approx(2 * _cv(noisy))

    def test_the_floor_uses_the_noise_multiplier_and_the_objective_gain(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_objective: Objective,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        GIVEN NOISE_MULTIPLIER 3 and a primary objective asking for 15 %
        WHEN baseline runs on the design baseline (CV 1.96 %)
        THEN the floor is max(3 x CV, 15 %) = 15 %, a warning (above 10 %)
        """
        monkeypatch.setattr(settings, "NOISE_MULTIPLIER", 3.0)
        demanding = sample_objective.model_copy(update={"min_relative_gain": 0.15})
        state = cast(EngineState, {**base_state, "objectives": [demanding]})

        delta = make_nodes(make_context())["baseline"](state)

        (warning,) = _coded(delta, "noisy_host")
        assert warning.level is EventLevel.warning
        assert warning.data["smallest_provable_gain"] == pytest.approx(0.15)


class TestProfileWithProfiler:
    def test_profiles_at_the_base_and_reports_skipped_workloads(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_project: Project,
        sample_workload: Workload,
    ) -> None:
        """
        GIVEN a profiler that finds one hotspot and skips one workload
        WHEN profile runs on a state pinned at SHA
        THEN it profiles this run's workloads at SHA, the state takes the
             profiler's hotspots (not the context's stand-ins) and a
             profile_skipped event carries the note
        """
        found = _hotspot(sample_project, sample_workload, "hot_loop")
        stand_in = _hotspot(sample_project, sample_workload, "stand_in")
        profiler = FakeProfiler([found], notes=("eval: not a Python command",))
        ctx = make_context(profiler=profiler, hotspots=(stand_in,))
        state = cast(EngineState, {**base_state, "base_commit": SHA})

        delta = make_nodes(ctx)["profile"](state)

        assert profiler.calls == [ProfileCall((sample_workload,), RUN_ID, SHA)]
        assert _items(delta, "hotspots", Hotspot) == [found]
        profiled, skipped = _events(delta)
        assert profiled.data["hotspots"] == 1
        assert skipped.data["code"] == "profile_skipped"
        assert "not a Python command" in skipped.message

    @pytest.mark.parametrize(
        "error",
        [
            EngineError(
                "profiled frame /home/dev/bridge/src/x.py is outside the worktree"
            ),
            RepoTamperedError("refs changed during profile"),
        ],
        ids=["editable-install", "tampered"],
    )
    def test_profiler_refusals_stop_the_run(
        self, make_context: ContextFactory, base_state: EngineState, error: EngineError
    ) -> None:
        """
        GIVEN a profiler that refuses an editable install or detects tampering
        WHEN profile runs
        THEN its EngineError propagates with the path it named
        """
        ctx = make_context(profiler=FakeProfiler(error=error))
        state = cast(EngineState, {**base_state, "base_commit": SHA})

        with pytest.raises(type(error), match=re.escape(str(error))):
            make_nodes(ctx)["profile"](state)

    def test_needs_a_pinned_commit(
        self, make_context: ContextFactory, base_state: EngineState
    ) -> None:
        """
        GIVEN a profiler but no pinned base commit
        WHEN profile runs
        THEN an EngineError says the commit is missing and nothing is profiled
        """
        profiler = FakeProfiler()

        with pytest.raises(EngineError, match="base commit"):
            make_nodes(make_context(profiler=profiler))["profile"](base_state)
        assert profiler.calls == []


class TestTrialsRunningBudget:
    @pytest.fixture
    def three(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
        h2_protected: Hypothesis,
        h3_noise: Hypothesis,
        design_scripts: dict[str, ScriptedOutcome],
    ) -> Callable[..., tuple[StubTrialRunner, dict[str, NodeFn], EngineState]]:
        """H1 (0.12 USD), H2 (0.08) and H3 (0.05) proposed, 0.25 of a 1.00 cap spent."""

        def build(
            **overrides: Any,
        ) -> tuple[StubTrialRunner, dict[str, NodeFn], EngineState]:
            runner = StubTrialRunner(design_scripts)
            nodes = make_nodes(
                make_context(
                    [h1_cache, h2_protected, h3_noise], runner=runner, **overrides
                )
            )
            state = _advance(nodes, base_state, _before("trials"))
            state = cast(EngineState, {**state, "max_cost_usd": 1.0, "cost_usd": 0.25})
            return runner, nodes, state

        return build

    def test_each_trial_is_offered_only_what_is_left(
        self,
        three: Callable[..., tuple[StubTrialRunner, dict[str, NodeFn], EngineState]],
    ) -> None:
        """
        GIVEN three proposed hypotheses and 0.75 USD left
        WHEN trials runs
        THEN the running total shrinks the offer before each trial
             (0.75, 0.63, 0.55), never the same remainder three times
        """
        runner, nodes, state = three()

        delta = nodes["trials"](state)

        assert runner.budgets == [
            pytest.approx(0.75),
            pytest.approx(0.63),
            pytest.approx(0.55),
        ]
        assert delta["cost_usd"] == pytest.approx(0.50)
        assert "budget_exhausted" not in delta

    def test_stops_before_a_trial_that_cannot_afford_one_request(
        self,
        three: Callable[..., tuple[StubTrialRunner, dict[str, NodeFn], EngineState]],
        h3_noise: Hypothesis,
    ) -> None:
        """
        GIVEN min_trial_budget_usd 0.60 and 0.75 USD left
        WHEN trials runs
        THEN H1 (offered 0.75) and H2 (0.63) run, H3 (0.55 < 0.60) never
             starts and stays proposed, a budget_exhausted warning counts it
             and the state flag is set
        """
        runner, nodes, state = three(min_trial_budget_usd=0.6)

        delta = nodes["trials"](state)

        assert runner.budgets == [pytest.approx(0.75), pytest.approx(0.63)]
        assert delta["budget_exhausted"] is True
        assert delta["cost_usd"] == pytest.approx(0.45)
        (exhausted,) = _coded(delta, "budget_exhausted")
        assert exhausted.level is EventLevel.warning
        assert exhausted.phase is RunPhase.trials
        assert exhausted.data["remaining_usd"] == pytest.approx(0.55)
        assert exhausted.data["min_trial_budget_usd"] == pytest.approx(0.6)
        assert exhausted.data["not_started"] == 1
        statuses = {h.id: h.status for h in _items(delta, "hypotheses", Hypothesis)}
        assert statuses[h3_noise.id] is HypothesisStatus.proposed
        summary = [e for e in _events(delta) if "code" not in e.data]
        assert summary[0].data["trials"] == 2

    def test_stops_when_the_cap_is_spent_exactly(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
        h3_noise: Hypothesis,
        design_scripts: dict[str, ScriptedOutcome],
    ) -> None:
        """
        GIVEN a 0.12 USD cap and H1 costing exactly 0.12
        WHEN trials runs H1 then H3
        THEN H1 runs, and with nothing left H3 never starts
        """
        runner = StubTrialRunner(design_scripts)
        nodes = make_nodes(make_context([h1_cache, h3_noise], runner=runner))
        state = _advance(nodes, base_state, _before("trials"))
        state = cast(EngineState, {**state, "max_cost_usd": 0.12})

        delta = nodes["trials"](state)

        assert runner.budgets == [pytest.approx(0.12)]
        assert delta["budget_exhausted"] is True

    def test_refuses_a_trial_that_spent_more_than_it_was_offered(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
        design_scripts: dict[str, ScriptedOutcome],
    ) -> None:
        """
        GIVEN a runner whose trial reports 9.00 USD against a 5.00 USD offer
        WHEN trials runs
        THEN an EngineError names the overspend and nothing is saved
        """
        runner = _TamperingRunner(StubTrialRunner(design_scripts), {"cost_usd": 9.0})
        ctx = make_context([h1_cache], runner=runner)
        nodes = make_nodes(ctx)
        state = _advance(nodes, base_state, _before("trials"))

        with pytest.raises(EngineError, match="cost_usd 9.0 exceeds its budget"):
            nodes["trials"](state)
        assert ctx.repository.list_trials(RUN_ID) == ()


class TestRouterBudget:
    def test_an_exhausted_budget_goes_straight_to_combine(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
        h3_noise: Hypothesis,
    ) -> None:
        """
        GIVEN round 1 of 3, an untrialled candidate left and nothing kept,
              but the budget exhausted
        WHEN after_verdicts routes
        THEN the run goes to combine instead of spinning empty rounds
        """
        ctx = make_context([h1_cache, h3_noise])
        base_state["round"] = 1
        base_state["trials"] = [Trial(hypothesis_id=h1_cache.id, round=1)]
        base_state["budget_exhausted"] = True

        assert make_router(ctx)(base_state) == "combine"

    def test_pending_approval_still_comes_first(
        self, make_context: ContextFactory, base_state: EngineState
    ) -> None:
        """
        GIVEN a pending approval and an exhausted budget
        WHEN after_verdicts routes
        THEN the human is asked first
        """
        base_state["pending_approval_ids"] = ["verdict"]
        base_state["budget_exhausted"] = True

        assert make_router(make_context())(base_state) == "approval_gate"


class TestVerdictsMergeViolations:
    def test_extra_protected_paths_from_connect_reject(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
        design_scripts: dict[str, ScriptedOutcome],
    ) -> None:
        """
        GIVEN connect protected the harness run.sh and H1 touched it
        WHEN verdicts runs
        THEN H1 is rejected for a protected_path violation on run.sh
        """
        scripts = {
            h1_cache.title: replace(
                design_scripts[h1_cache.title], touched_paths=("run.sh",)
            )
        }
        nodes = make_nodes(make_context([h1_cache], scripts))
        state = _advance(nodes, base_state, _before("verdicts"))
        state["extra_protected"] = ["run.sh"]

        (verdict,) = _items(nodes["verdicts"](state), "verdicts", Verdict)

        assert verdict.outcome is VerdictOutcome.reject
        (violation,) = verdict.violations
        assert (violation.rule, violation.path, violation.pattern) == (
            ViolationRule.protected_path,
            "run.sh",
            "run.sh",
        )

    def test_capture_violations_join_and_duplicates_are_dropped(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN a failed trial whose runner reported a symlink and the same
              protected test file the node's own check finds
        WHEN verdicts runs
        THEN the verdict lists the node's protected_path violation, then the
             runner's symlink, without repeating the (rule, path, pattern)
        """
        nodes = make_nodes(make_context([h1_cache]))
        state = _advance(nodes, base_state, _before("verdicts"))
        runner_saw = (
            Violation(
                rule=ViolationRule.protected_path,
                path="tests/test_x.py",
                pattern="**/tests/**",
                message="runner saw it too",
            ),
            Violation(
                rule=ViolationRule.forbidden_file_mode,
                path="src/fast.py",
                message="new symlink",
            ),
        )
        state["round_trials"] = [
            t.model_copy(
                update={
                    "touched_paths": ("tests/test_x.py", "src/fast.py"),
                    "violations": runner_saw,
                    "status": TrialStatus.failed,
                }
            )
            for t in state["round_trials"]
        ]

        (verdict,) = _items(nodes["verdicts"](state), "verdicts", Verdict)

        assert verdict.outcome is VerdictOutcome.reject
        assert [(v.rule, v.path) for v in verdict.violations] == [
            (ViolationRule.protected_path, "tests/test_x.py"),
            (ViolationRule.forbidden_file_mode, "src/fast.py"),
        ]
        assert verdict.violations[0].message != "runner saw it too"


class TestCombineWithCombiner:
    def test_a_held_re_test_keeps_the_applied_changes(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_project: Project,
        sample_workload: Workload,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN H1 kept and a combiner whose ABAB re-test of the tip holds,
              tests included
        WHEN combine runs
        THEN the combiner gets H1 as a KeptChange at the base, the verdict
             is keep, H1's verdict stays kept and the Combination records it
        """
        nodes = make_nodes(make_context([h1_cache]))
        state = _committed(_advance(nodes, base_state, _before("combine")))
        trial, verdict = _trial_of(state, h1_cache), _verdict_of(state, h1_cache)
        combiner = FakeCombiner([_measured(sample_workload.id, [trial.id])])
        nodes = make_nodes(make_context([h1_cache], combiner=combiner))
        ranked = next(h for h in state["hypotheses"] if h.id == h1_cache.id)

        delta = nodes["combine"](state)

        assert combiner.calls == [
            CombineCall(
                RUN_ID,
                state["project"],
                SHA,
                (
                    KeptChange(
                        trial_id=trial.id,
                        hypothesis_id=h1_cache.id,
                        verdict_id=verdict.id,
                        commit=trial.commit or "",
                        score=ranked.score,
                        gain=verdict.gain,
                    ),
                ),
                (sample_workload,),
            )
        ]
        assert set(delta) == {"phase", "kept_verdict_ids", "combination", "events"}
        assert delta["kept_verdict_ids"] == [verdict.id]
        combination = delta["combination"]
        assert isinstance(combination, Combination)
        assert combination.holds is True
        assert combination.base_commit == SHA
        assert combination.tip_commit == TIP
        assert combination.applied_trial_ids == (trial.id,)
        assert combination.fallback_trial_id is None
        outcomes = {r.judge: r.outcome for r in combination.judge_results}
        assert outcomes["speed"] is JudgeOutcome.passed
        assert outcomes["tests"] is JudgeOutcome.passed
        assert "held" in combination.summary
        event = _only_event(delta)
        assert event.data["holds"] is True
        assert event.data["delivered"] == 1

    def test_the_combiner_gets_the_baselines_passing_test_count(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_workload: Workload,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN a baseline whose test suite counted 4 passing tests
        WHEN combine runs
        THEN the combiner gets baseline_count=4, so the tip's suite must
             reach the baseline's count, as every trial's must (the fallback
             goes through the same re-test)
        """
        nodes = make_nodes(make_context([h1_cache]))
        state = _committed(_advance(nodes, base_state, _before("combine")))
        baseline = state["baseline"]
        assert baseline is not None
        counted = [
            m.model_copy(update={"hardware": {**m.hardware, "tests_counted": 4}})
            if m.metric == METRIC_TESTS_PASSED
            else m
            for m in baseline.measurements
        ]
        assert any(m.metric == METRIC_TESTS_PASSED for m in counted)
        state = cast(
            EngineState,
            {
                **state,
                "baseline": baseline.model_copy(update={"measurements": counted}),
            },
        )
        trial = _trial_of(state, h1_cache)
        combiner = FakeCombiner([_measured(sample_workload.id, [trial.id])])
        nodes = make_nodes(make_context([h1_cache], combiner=combiner))

        nodes["combine"](state)

        assert [call.baseline_count for call in combiner.calls] == [4]

    @pytest.mark.parametrize(
        ("combined", "reason"),
        [
            pytest.param(_rows("W", FAST, tests=None), "tests", id="tests-row-missing"),
            pytest.param(_rows("W", FAST, tests=0.0), "tests", id="tests-failing"),
            pytest.param(
                _rows("W", FAST, val_loss=(0.0,) * 5),
                "guardrail",
                id="guardrail-inconclusive",
            ),
            pytest.param(_rows("W", SLOW), METRIC_WALL_TIME_S, id="no-gain"),
        ],
    )
    def test_a_failed_re_test_of_one_change_keeps_nothing(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_workload: Workload,
        h1_cache: Hypothesis,
        combined: tuple[Measurement, ...],
        reason: str,
    ) -> None:
        """
        GIVEN H1 alone kept and a re-test whose tests row is missing or
              failing, whose guardrail is inconclusive, or with no gain
        WHEN combine runs
        THEN the combination does not hold, no fallback runs (the only single
             change is the set that just failed) and nothing is kept
        """
        rows = tuple(
            m.model_copy(update={"workload_id": sample_workload.id}) for m in combined
        )
        baseline = _rows(
            sample_workload.id,
            SLOW,
            tests=None,
            val_loss=((0.0,) * 5 if reason == "guardrail" else (0.5,) * 5),
        )
        nodes = make_nodes(make_context([h1_cache]))
        state = _committed(_advance(nodes, base_state, _before("combine")))
        trial = _trial_of(state, h1_cache)
        combiner = FakeCombiner(
            [
                _measured(
                    sample_workload.id, [trial.id], baseline=baseline, combined=rows
                )
            ]
        )

        delta = make_nodes(make_context([h1_cache], combiner=combiner))["combine"](
            state
        )

        assert len(combiner.calls) == 1
        assert delta["kept_verdict_ids"] == []
        combination = delta["combination"]
        assert isinstance(combination, Combination)
        assert combination.holds is False
        assert combination.fallback_trial_id is None
        assert "no fallback" in combination.summary
        assert "nothing delivered" in combination.summary
        assert reason in combination.summary

    def test_an_incomplete_interleaved_baseline_does_not_hold(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_workload: Workload,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN a re-test whose A runs (the interleaved baseline) are missing
        WHEN combine runs
        THEN the combination is rejected for the missing measurements
        """
        nodes = make_nodes(make_context([h1_cache]))
        state = _committed(_advance(nodes, base_state, _before("combine")))
        trial = _trial_of(state, h1_cache)
        combiner = FakeCombiner(
            [_measured(sample_workload.id, [trial.id], baseline=())]
        )

        delta = make_nodes(make_context([h1_cache], combiner=combiner))["combine"](
            state
        )

        combination = delta["combination"]
        assert isinstance(combination, Combination)
        assert combination.holds is False
        assert "interleaved baseline" in combination.summary

    def test_kept_changes_go_in_score_order_then_by_hypothesis_id(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_project: Project,
        sample_workload: Workload,
        h1_cache: Hypothesis,
        h4_behaviour: Hypothesis,
    ) -> None:
        """
        GIVEN two equal-score efficiency keeps (ids tie-b, tie-a) and an
              approved lower-score behaviour change
        WHEN combine runs
        THEN the combiner gets tie-a, tie-b, then the approved change
        """
        tie_b = h1_cache.model_copy(update={"id": "tie-b"})
        tie_a = h1_cache.model_copy(update={"id": "tie-a"})
        candidates = [tie_b, tie_a, h4_behaviour]
        nodes = make_nodes(make_context(candidates, max_hypotheses_per_round=3))
        state = _committed(_advance(nodes, base_state, _before("combine")))
        state["approval"] = ApprovalDecision(
            approved_verdict_ids=(_verdict_of(state, h4_behaviour).id,), approver="pk"
        )
        applied = [t.id for t in state["trials"]]
        combiner = FakeCombiner([_measured(sample_workload.id, applied)])

        delta = make_nodes(make_context(candidates, combiner=combiner))["combine"](
            state
        )

        (call,) = combiner.calls
        assert [c.hypothesis_id for c in call.kept] == [
            "tie-a",
            "tie-b",
            h4_behaviour.id,
        ]
        assert sorted(cast(list[str], delta["kept_verdict_ids"])) == sorted(
            v.id for v in state["verdicts"]
        )

    def test_falls_back_to_the_best_gain_with_an_id_tie_break(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_project: Project,
        sample_workload: Workload,
    ) -> None:
        """
        GIVEN three kept changes: hyp-b and hyp-a with the same 41.7 % gain,
              hyp-c with less, and a greedy re-test that fails its tests
        WHEN combine runs
        THEN one fallback re-tests hyp-a alone (best gain, smaller id); it
             holds, so only hyp-a's verdict is kept
        """
        hyp_b = _efficiency(sample_project, "hyp-b", "b-fast")
        hyp_a = _efficiency(sample_project, "hyp-a", "a-fast")
        hyp_c = _efficiency(sample_project, "hyp-c", "c-less", expected_gain=0.9)
        scripts = {
            "b-fast": _winning(FAST),
            "a-fast": _winning(FAST),
            "c-less": _winning((1.40, 1.38, 1.42, 1.40, 1.40)),
        }
        candidates = [hyp_b, hyp_a, hyp_c]
        nodes = make_nodes(make_context(candidates, scripts))
        state = _committed(_advance(nodes, base_state, _before("combine")))
        assert all(v.outcome is VerdictOutcome.keep for v in state["verdicts"])
        all_ids = [t.id for t in state["trials"]]
        trial_a = _trial_of(state, hyp_a)
        combiner = FakeCombiner(
            [
                _measured(
                    sample_workload.id,
                    all_ids,
                    combined=_rows(sample_workload.id, FAST, tests=0.0),
                ),
                _measured(sample_workload.id, [trial_a.id], tip="d" * 40),
            ]
        )

        delta = make_nodes(make_context(candidates, scripts, combiner=combiner))[
            "combine"
        ](state)

        greedy, fallback = combiner.calls
        assert [c.hypothesis_id for c in greedy.kept] == ["hyp-c", "hyp-a", "hyp-b"]
        assert [c.hypothesis_id for c in fallback.kept] == ["hyp-a"]
        assert delta["kept_verdict_ids"] == [_verdict_of(state, hyp_a).id]
        combination = delta["combination"]
        assert isinstance(combination, Combination)
        assert combination.holds is True
        assert combination.fallback_trial_id == trial_a.id
        assert combination.tip_commit == "d" * 40
        assert combination.applied_trial_ids == (trial_a.id,)
        assert "fallback" in combination.summary

    def test_the_fallback_never_re_tests_the_set_that_just_failed(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_project: Project,
        sample_workload: Workload,
    ) -> None:
        """
        GIVEN two kept changes where the best one applied alone (the other
              conflicted) and that re-test failed
        WHEN combine runs
        THEN the fallback re-tests the other change, not the failed best one;
             when that fails too nothing is kept and both skips and attempts
             are in the summary
        """
        best = _efficiency(sample_project, "best", "best-fast")
        other = _efficiency(sample_project, "other", "other-less")
        scripts = {
            "best-fast": _winning(FAST),
            "other-less": _winning((1.40, 1.38, 1.42, 1.40, 1.40)),
        }
        candidates = [best, other]
        nodes = make_nodes(make_context(candidates, scripts))
        state = _committed(_advance(nodes, base_state, _before("combine")))
        trial_best, trial_other = _trial_of(state, best), _trial_of(state, other)
        skip = CombineSkip(
            trial_id=trial_other.id, reason="conflict", paths=("dedupe/core.py",)
        )
        failing = _rows(sample_workload.id, FAST, tests=0.0)
        combiner = FakeCombiner(
            [
                _measured(
                    sample_workload.id,
                    [trial_best.id],
                    skipped=[skip],
                    combined=failing,
                ),
                _measured(sample_workload.id, [trial_other.id], combined=failing),
            ]
        )

        delta = make_nodes(make_context(candidates, scripts, combiner=combiner))[
            "combine"
        ](state)

        assert [c.trial_id for c in combiner.calls[1].kept] == [trial_other.id]
        assert delta["kept_verdict_ids"] == []
        combination = delta["combination"]
        assert isinstance(combination, Combination)
        assert combination.holds is False
        assert combination.fallback_trial_id == trial_other.id
        assert combination.skipped == (skip,)
        assert "conflict" in combination.summary
        assert "dedupe/core.py" in combination.summary
        assert "nothing delivered" in combination.summary

    def test_when_both_fail_deliver_is_report_only_and_lessons_stand(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_project: Project,
        sample_workload: Workload,
    ) -> None:
        """
        GIVEN two kept changes whose combination and best single change both
              fail their re-test
        WHEN combine, deliver and learn run
        THEN nothing is kept, the delivery is report_only with no publish,
             and the lessons still record both individual keeps
        """
        one = _efficiency(sample_project, "one", "one-fast")
        two = _efficiency(sample_project, "two", "two-fast")
        scripts = {"one-fast": _winning(FAST), "two-fast": _winning(FAST)}
        failing = _rows(sample_workload.id, FAST, tests=0.0)
        base_nodes = make_nodes(make_context([one, two], scripts))
        state = _committed(_advance(base_nodes, base_state, _before("combine")))
        ids = [t.id for t in state["trials"]]
        combiner = FakeCombiner(
            [
                _measured(sample_workload.id, ids, combined=failing),
                _measured(
                    sample_workload.id, [_trial_of(state, one).id], combined=failing
                ),
            ]
        )
        publisher = FakePublisher("diff")
        nodes = make_nodes(
            make_context([one, two], scripts, combiner=combiner, publisher=publisher)
        )

        state = _apply(state, nodes["combine"](state))
        delivery = nodes["deliver"](state)["delivery"]
        lessons = _items(nodes["learn"](state), "lessons", Lesson)

        assert state["kept_verdict_ids"] == []
        assert isinstance(delivery, Delivery)
        assert delivery.kind is DeliveryKind.report_only
        assert publisher.calls == []
        assert [lesson.outcome for lesson in lessons] == [VerdictOutcome.keep] * 2

    def test_a_re_test_that_applied_nothing_says_so(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_workload: Workload,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN a combiner that applies nothing (H1 skipped) on the greedy merge
              and on the fallback, yet reports passing B runs both times
        WHEN combine runs
        THEN nothing is kept and the summary says both re-tests applied
             nothing instead of quoting a keep verdict as the failure reason
        """
        nodes = make_nodes(make_context([h1_cache]))
        state = _committed(_advance(nodes, base_state, _before("combine")))
        trial = _trial_of(state, h1_cache)
        skip = CombineSkip(trial_id=trial.id, reason="conflict", paths=("a.py",))
        combiner = FakeCombiner(
            [
                _measured(sample_workload.id, [], skipped=[skip]),
                _measured(sample_workload.id, [], skipped=[skip]),
            ]
        )
        nodes = make_nodes(make_context([h1_cache], combiner=combiner))

        delta = nodes["combine"](state)

        assert delta["kept_verdict_ids"] == []
        combination = delta["combination"]
        assert isinstance(combination, Combination)
        assert combination.holds is False
        assert combination.fallback_trial_id == trial.id
        summary = combination.summary
        assert "re-test did not hold: nothing was applied (tip is the base)" in summary
        assert (
            f"fallback re-tested trial {trial.id[:8]} alone and did not hold: "
            "nothing was applied (tip is the base)"
        ) in summary
        assert "all judges passed" not in summary

    def test_nothing_kept_never_calls_the_combiner(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h3_noise: Hypothesis,
    ) -> None:
        """
        GIVEN only an inconclusive verdict
        WHEN combine runs with a combiner
        THEN the combiner is not called and nothing is kept
        """
        combiner = FakeCombiner([])
        nodes = make_nodes(make_context([h3_noise], combiner=combiner))
        state = _committed(_advance(nodes, base_state, _before("combine")))

        delta = nodes["combine"](state)

        assert combiner.calls == []
        assert delta["kept_verdict_ids"] == []
        assert "combination" not in delta
        assert "nothing" in _only_event(delta).message

    def test_a_kept_trial_without_a_commit_cannot_be_combined(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN a kept trial the runner never committed
        WHEN combine runs with a combiner
        THEN an EngineError names the verdict and the combiner is not called
        """
        combiner = FakeCombiner([])
        nodes = make_nodes(make_context([h1_cache], combiner=combiner))
        state = _advance(nodes, base_state, _before("combine"))
        state["base_commit"] = SHA

        with pytest.raises(EngineError, match="no committed trial"):
            nodes["combine"](state)
        assert combiner.calls == []

    def test_needs_a_pinned_commit(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN a kept change but no pinned base commit
        WHEN combine runs with a combiner
        THEN an EngineError says the commit is missing
        """
        combiner = FakeCombiner([])
        nodes = make_nodes(make_context([h1_cache], combiner=combiner))
        state = _committed(_advance(nodes, base_state, _before("combine")))
        state["base_commit"] = None

        with pytest.raises(EngineError, match="base commit"):
            nodes["combine"](state)

    @pytest.mark.parametrize(
        "problem", ["unknown-applied", "unknown-skipped", "twice", "bad-tip"]
    )
    def test_refuses_an_untrustworthy_combiner_result(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_workload: Workload,
        h1_cache: Hypothesis,
        problem: str,
    ) -> None:
        """
        GIVEN a combiner that reports a trial it was not given, a trial twice,
              or a tip that is not a commit id
        WHEN combine runs
        THEN an EngineError refuses the result
        """
        nodes = make_nodes(make_context([h1_cache]))
        state = _committed(_advance(nodes, base_state, _before("combine")))
        trial_id = _trial_of(state, h1_cache).id
        stranger = CombineSkip(trial_id="stranger", reason="conflict")
        measured = {
            "unknown-applied": _measured(sample_workload.id, ["stranger"]),
            "unknown-skipped": _measured(
                sample_workload.id, [trial_id], skipped=[stranger]
            ),
            "twice": _measured(sample_workload.id, [trial_id, trial_id]),
            "bad-tip": _measured(sample_workload.id, [trial_id], tip="--evil"),
        }[problem]
        combiner = FakeCombiner([measured])

        with pytest.raises(EngineError, match="combiner"):
            make_nodes(make_context([h1_cache], combiner=combiner))["combine"](state)


class TestDeliverWithPublisher:
    def _combined_state(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        workload: Workload,
        h1: Hypothesis,
    ) -> EngineState:
        nodes = make_nodes(make_context([h1]))
        state = _committed(_advance(nodes, base_state, _before("combine")))
        trial = _trial_of(state, h1)
        combiner = FakeCombiner([_measured(workload.id, [trial.id])])
        return _apply(
            state, make_nodes(make_context([h1], combiner=combiner))["combine"](state)
        )

    def test_publishes_the_combined_tip_and_uses_its_diff(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_workload: Workload,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN a held combination of H1 at tip TIP on base SHA
        WHEN deliver runs with a publisher
        THEN the publisher creates engine/run-<id> at TIP from SHA, and the
             delivery carries its capped diff and the tip commit
        """
        state = self._combined_state(
            make_context, base_state, sample_workload, h1_cache
        )
        publisher = FakePublisher("diff --git a/x b/x")

        delta = make_nodes(make_context([h1_cache], publisher=publisher))["deliver"](
            state
        )

        branch = f"engine/run-{RUN_ID}"
        assert publisher.calls == [PublishCall(state["project"], branch, TIP, SHA)]
        delivery = delta["delivery"]
        assert isinstance(delivery, Delivery)
        assert delivery.kind is DeliveryKind.branch
        assert delivery.branch == branch
        assert delivery.commit == TIP
        assert delivery.combined_diff == "diff --git a/x b/x"
        assert delivery.verdict_ids == tuple(state["kept_verdict_ids"])
        assert _only_event(delta).data == {
            "kind": "branch",
            "kept": 1,
            "branch": branch,
            "commit": TIP,
        }

    def test_refuses_the_default_branch_before_publishing(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_workload: Workload,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN a project whose default branch is the delivery branch
        WHEN deliver runs with a publisher
        THEN a DeliveryError is raised and nothing is published
        """
        state = self._combined_state(
            make_context, base_state, sample_workload, h1_cache
        )
        state["project"] = state["project"].model_copy(
            update={"default_branch": f"engine/run-{RUN_ID}"}
        )
        publisher = FakePublisher()

        with pytest.raises(DeliveryError):
            make_nodes(make_context([h1_cache], publisher=publisher))["deliver"](state)
        assert publisher.calls == []

    @pytest.mark.parametrize("missing", ["combination", "held", "base"])
    def test_publishing_needs_a_held_combination_at_a_pinned_base(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_workload: Workload,
        h1_cache: Hypothesis,
        missing: str,
    ) -> None:
        """
        GIVEN kept changes but no combination, one that did not hold, or no base
        WHEN deliver runs with a publisher
        THEN an EngineError refuses to publish anything untested
        """
        state = self._combined_state(
            make_context, base_state, sample_workload, h1_cache
        )
        combination = state["combination"]
        assert combination is not None
        if missing == "combination":
            state["combination"] = None
        elif missing == "held":
            state["combination"] = combination.model_copy(update={"holds": False})
        else:
            state["base_commit"] = None
        publisher = FakePublisher()

        with pytest.raises(EngineError, match="publish"):
            make_nodes(make_context([h1_cache], publisher=publisher))["deliver"](state)
        assert publisher.calls == []


class TestReportRunConditions:
    def test_step1_runs_say_what_was_not_checked(
        self, make_context: ContextFactory, base_state: EngineState
    ) -> None:
        """
        GIVEN a run with no Step 2 seams
        WHEN deliver writes the report
        THEN the Run conditions section says the commit was not pinned, the
             isolation not checked, defines peak RSS and lists no trial refs
        """
        nodes = make_nodes(make_context())
        report = cast(
            Delivery, nodes["deliver"](base_state)["delivery"]
        ).report_markdown

        assert "**Run conditions**" in report
        assert "- Measured commit: not pinned" in report
        assert "- Isolation: not checked" in report
        assert "largest single process among the waited-for descendants" in report
        assert "- Trial refs: none" in report
        assert "for-each-ref" not in report

    def test_step2_runs_list_every_condition_and_the_cleanup_command(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_project: Project,
        sample_workload: Workload,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN a run whose preflight saw 2 dirty entries and best-effort
              networking, a workload with ignored inputs, a held combination
              and a committed trial
        WHEN deliver writes the report
        THEN Run conditions lists the sha, the dirty count, both isolation
             modes, the noise floor, the ignored inputs, the combination
             summary, the trial ref and a copyable cleanup command
        """
        with_inputs = sample_workload.model_copy(update={"inputs": {"steps": 20}})
        state = cast(EngineState, {**base_state, "workloads": [with_inputs]})
        preflight = FakePreflight(
            _preflight_report([with_inputs], dirty=("a", "b"), network="best_effort")
        )
        nodes = make_nodes(make_context([h1_cache], preflight=preflight))
        state = _committed(_advance(nodes, state, _before("combine")))
        trial = _trial_of(state, h1_cache)
        combiner = FakeCombiner([_measured(sample_workload.id, [trial.id])])
        nodes = make_nodes(make_context([h1_cache], combiner=combiner))
        state = _apply(state, nodes["combine"](state))

        report = cast(Delivery, nodes["deliver"](state)["delivery"]).report_markdown

        combination = state["combination"]
        assert combination is not None
        ref = f"refs/heads/engine/trial-{RUN_ID}-{h1_cache.id}"
        assert f"- Measured commit: {SHA}" in report
        assert "- Uncommitted changes ignored: 2" in report
        assert "- Isolation: network best_effort, filesystem required" in report
        assert (
            f"- Noise floor: smallest provable gain train-step {2 * _cv(SLOW):.1%}"
            in report
        )
        assert "- Workload inputs ignored: train-step" in report
        assert "- Combination: " + combination.summary[:40] in report
        assert f"- Trial refs: {ref}" in report
        assert (
            "```\ngit update-ref --stdin <<'EOF'\n"
            f"delete {ref} {trial.commit}\nEOF\n```"
        ) in report

    def test_run_conditions_are_sanitised(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        sample_workload: Workload,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN a combiner skip whose conflict path tries to inject a heading,
              raw HTML and a link, and a workload name with a line break
        WHEN deliver writes the report
        THEN the report still has one heading, no raw HTML and no link
        """
        hostile = "x\n\n## Approved <img src=x> [merge](https://attacker.example)"
        named = sample_workload.model_copy(update={"name": hostile, "inputs": {"a": 1}})
        state = cast(EngineState, {**base_state, "workloads": [named]})
        nodes = make_nodes(make_context([h1_cache]))
        state = _committed(_advance(nodes, state, _before("combine")))
        trial = _trial_of(state, h1_cache)
        skip = CombineSkip(trial_id=trial.id, reason=hostile, paths=(hostile,))
        combiner = FakeCombiner(
            [
                _measured(sample_workload.id, [], skipped=[skip]),
                _measured(sample_workload.id, [trial.id]),
            ]
        )
        nodes = make_nodes(make_context([h1_cache], combiner=combiner))
        state = _apply(state, nodes["combine"](state))

        report = cast(Delivery, nodes["deliver"](state)["delivery"]).report_markdown

        combination = state["combination"]
        assert combination is not None
        assert combination.holds is True
        assert combination.fallback_trial_id == trial.id
        assert "applied nothing" in combination.summary
        assert "re-test did not hold: nothing was applied" in combination.summary
        assert (
            "all judges passed; efficiency"
            not in combination.summary.split("fallback")[0]
        )
        lines = report.splitlines()
        assert [line for line in lines if line.startswith("#")] == [lines[0]]
        assert "<img" not in report
        assert re.search(r"(?<!\\)\]\(", report) is None
        assert re.search(r"(?i)www(?!\\)\.", report) is None

    def test_an_unsafe_ref_prefix_omits_the_cleanup_command(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN a committed trial but a branch prefix with characters a shell
              would interpret
        WHEN deliver writes the report
        THEN the trial ref is listed but no cleanup command is printed
        """
        nodes = make_nodes(make_context([h1_cache]))
        state = _committed(_advance(nodes, base_state, _before("deliver")))
        state["kept_verdict_ids"] = []

        report = cast(
            Delivery,
            make_nodes(make_context([h1_cache], branch_prefix="eng'$(x)/"))["deliver"](
                state
            )["delivery"],
        ).report_markdown

        assert "- Trial refs: refs/heads/engine/trial-" in report
        assert "for-each-ref" not in report


class TestReportTestCount:
    @pytest.mark.parametrize(
        ("command", "says"),
        [
            (None, "- Test count: no test command"),
            (
                ("/usr/bin/python3", "-m", "unittest"),
                "- Test count: verified from the unittest summary",
            ),
            (("pytest", "tests"), "- Test count: verified from the pytest summary"),
            (
                ("./run_tests.sh",),
                "- Test count: not verified (the test command is neither unittest"
                " nor pytest, so the suite passed on its exit code alone",
            ),
        ],
        ids=["none", "unittest", "pytest", "wrapper"],
    )
    def test_the_report_says_whether_the_test_count_was_verified(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        command: tuple[str, ...] | None,
        says: str,
    ) -> None:
        """
        GIVEN no test command, a unittest or pytest command, or a wrapper
              script the engine cannot read a summary from
        WHEN deliver writes the report
        THEN Run conditions says whether a suite that runs fewer tests than
             the baseline would have been caught
        """
        project = base_state["project"].model_copy(update={"test_command": command})
        state = cast(EngineState, {**base_state, "project": project})

        delivery = make_nodes(make_context())["deliver"](state)["delivery"]

        assert says in cast(Delivery, delivery).report_markdown


class TestTrialRefCleanup:
    def test_the_command_names_exactly_this_runs_refs_at_their_commits(self) -> None:
        """
        GIVEN trials of run 'nightly' (one committed twice, one never) and a
              run 'nightly-2' whose ref a 'trial-nightly-*' pattern would match
        WHEN the cleanup command is built for 'nightly'
        THEN it deletes this run's committed refs only, each once at the
             commit it was left at, in one update-ref transaction
        """
        mine = "refs/heads/engine/trial-nightly-h1"
        trials = [
            Trial(hypothesis_id="h1", round=1, branch="engine/trial-nightly-h1", commit="1" * 40),
            Trial(hypothesis_id="h1", round=2, branch="engine/trial-nightly-h1", commit="2" * 40),
            Trial(hypothesis_id="h2", round=1, branch="engine/trial-nightly-h2"),
        ]  # fmt: skip

        lines = trial_ref_cleanup(trials, "nightly", "engine/")

        assert lines == [
            "git update-ref --stdin <<'EOF'",
            f"delete {mine} {'2' * 40}",
            "EOF",
        ]

    @pytest.mark.parametrize(
        ("branch", "commit", "prefix"),
        [
            ("engine/trial-r-h1", "1" * 40, "eng'$(x)/"),
            ("engine/trial-r-h1;rm", "1" * 40, "engine/"),
            ("engine/trial-r-h1", "not-a-commit", "engine/"),
        ],
        ids=["prefix", "ref", "commit"],
    )
    def test_no_command_when_a_piece_is_not_plain(
        self, branch: str, commit: str, prefix: str
    ) -> None:
        trial = Trial(hypothesis_id="h1", round=1, branch=branch, commit=commit)

        assert trial_ref_cleanup([trial], "r", prefix) == []

    def test_no_command_without_a_committed_trial(self) -> None:
        assert (
            trial_ref_cleanup([Trial(hypothesis_id="h1", round=1)], "r", "engine/")
            == []
        )

    def test_the_printed_command_deletes_the_refs_and_leaves_the_other_run(
        self, tmp_path: Path
    ) -> None:
        """
        GIVEN a repository with the refs of runs 'nightly' and 'nightly-2'
        WHEN the report's command for 'nightly' is fed to git as printed
        THEN only 'nightly''s ref is gone
        """
        env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": os.devnull,
               "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}  # fmt: skip

        def git(*args: str, stdin: str | None = None) -> str:
            return subprocess.run(
                ["git", "-C", str(tmp_path), *args],
                env=env, input=stdin, capture_output=True, text=True, check=True,
            ).stdout.strip()  # fmt: skip

        git("init", "-q")
        git("commit", "-q", "--allow-empty", "-m", "base")
        head = git("rev-parse", "HEAD")
        for ref in ("engine/trial-nightly-h1", "engine/trial-nightly-2-h1"):
            git("update-ref", f"refs/heads/{ref}", head)
        trial = Trial(
            hypothesis_id="h1", round=1, branch="engine/trial-nightly-h1", commit=head
        )
        first, *body, last = trial_ref_cleanup([trial], "nightly", "engine/")
        assert (first, last) == ("git update-ref --stdin <<'EOF'", "EOF")

        git("update-ref", "--stdin", stdin="".join(f"{line}\n" for line in body))

        refs = git("for-each-ref", "--format=%(refname)", "refs/heads/engine/")
        assert refs.splitlines() == ["refs/heads/engine/trial-nightly-2-h1"]


# ---------------------------------------------------------------------------
# What a failing node already spent (and ran) survives its exception
# ---------------------------------------------------------------------------


class _RaisingRunner:
    """Delegates to the stub, but raises ``error`` for one title after noting
    ``spend`` on it (what the real runner does when a trial is aborted)."""

    def __init__(
        self,
        inner: StubTrialRunner,
        title: str,
        error: Exception,
        spend: tuple[float, int] = (0.0, 0),
    ) -> None:
        self._inner, self._title, self._error, self._spend = inner, title, error, spend

    def run(
        self,
        hypothesis: Hypothesis,
        workloads: Sequence[Workload],
        baseline: Baseline,
        *,
        round: int,
        branch: str,
        budget_usd: float,
        brief: TrialBrief,
    ) -> Trial:
        if hypothesis.title == self._title:
            add_spend(self._error, *self._spend)
            raise self._error
        return self._inner.run(
            hypothesis,
            workloads,
            baseline,
            round=round,
            branch=branch,
            budget_usd=budget_usd,
            brief=brief,
        )


class _SpendingUnderstander:
    """Records ``usd`` into the run's budget (a timed-out attempt), then raises."""

    def __init__(self, usd: float, tokens: int, error: Exception) -> None:
        self._usd, self._tokens, self._error = usd, tokens, error

    def understand(
        self,
        project: Project,
        workloads: Sequence[Workload],
        *,
        commit: str,
        budget: Budget,
    ) -> UnderstandResult:
        budget.record(self._usd, self._tokens)
        raise self._error


class TestProgressOfAFailingNode:
    @pytest.fixture
    def two(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
        h3_noise: Hypothesis,
        design_scripts: dict[str, ScriptedOutcome],
    ) -> Callable[[Any], tuple[dict[str, NodeFn], EngineState]]:
        """H1 (0.12 USD) then H3 proposed; 0.25 of 1.00 spent."""

        def build(runner: Any) -> tuple[dict[str, NodeFn], EngineState]:
            nodes = make_nodes(make_context([h1_cache, h3_noise], runner=runner))
            state = _advance(nodes, base_state, _before("trials"))
            update = {"max_cost_usd": 1.0, "cost_usd": 0.25, "tokens_used": 100}
            return nodes, cast(EngineState, {**state, **update})

        return build

    @pytest.mark.parametrize(
        "error",
        [RepoTamperedError("the repository changed"), RuntimeError("bug")],
        ids=["engine-error", "other"],
    )
    def test_an_aborted_trial_keeps_the_rounds_trials_and_every_cost(
        self,
        two: Callable[[Any], tuple[dict[str, NodeFn], EngineState]],
        design_scripts: dict[str, ScriptedOutcome],
        h1_cache: Hypothesis,
        h3_noise: Hypothesis,
        error: Exception,
    ) -> None:
        """
        GIVEN H1 run (0.12 USD) and H3 aborted after spending 0.05 USD
        WHEN trials runs
        THEN the error propagates carrying the node's progress: the running
             total with both trials' money, and H1's trial in round_trials
             and trials, H1 trialled and H3 still proposed
        """
        runner = _RaisingRunner(
            StubTrialRunner(design_scripts), h3_noise.title, error, (0.05, 30)
        )
        nodes, state = two(runner)

        with pytest.raises(type(error)) as raised:
            nodes["trials"](state)

        progress = progress_of(raised.value)
        assert progress["cost_usd"] == pytest.approx(0.25 + 0.12 + 0.05)
        [kept] = _items(progress, "round_trials", Trial)
        assert progress["tokens_used"] == 100 + kept.tokens_used + 30
        assert kept.hypothesis_id == h1_cache.id
        assert _items(progress, "trials", Trial) == [kept]
        statuses = {h.id: h.status for h in _items(progress, "hypotheses", Hypothesis)}
        assert statuses[h1_cache.id] is HypothesisStatus.trialled
        assert statuses[h3_noise.id] is HypothesisStatus.proposed

    def test_an_untrustworthy_trial_is_charged_at_most_its_offer(
        self,
        two: Callable[[Any], tuple[dict[str, NodeFn], EngineState]],
        design_scripts: dict[str, ScriptedOutcome],
    ) -> None:
        """
        GIVEN a runner reporting 9.00 USD for a trial offered 0.75 USD
        WHEN trials refuses it
        THEN the progress charges the 0.75 USD offered, never past the cap
        """
        runner = _TamperingRunner(StubTrialRunner(design_scripts), {"cost_usd": 9.0})
        nodes, state = two(runner)

        with pytest.raises(EngineError, match="exceeds its budget") as raised:
            nodes["trials"](state)

        assert progress_of(raised.value)["cost_usd"] == pytest.approx(1.0)

    def test_money_understand_spent_before_an_engine_error_is_kept(
        self, make_context: ContextFactory, base_state: EngineState
    ) -> None:
        """
        GIVEN 0.50 of a 2.00 cap spent, and an understander whose timed-out
              attempt was charged 0.53 USD before the cap stopped the retry
        WHEN understand runs
        THEN BudgetExceeded propagates with the 1.03 USD total as progress
        """
        understander = _SpendingUnderstander(0.53, 9000, BudgetExceeded("cap"))
        state = cast(
            EngineState,
            {
                **base_state,
                "base_commit": SHA,
                "max_cost_usd": 2.0,
                "cost_usd": 0.5,
                "tokens_used": 100,
            },
        )

        with pytest.raises(BudgetExceeded) as raised:
            make_nodes(make_context(understander=understander))["understand"](state)

        progress = progress_of(raised.value)
        assert progress == {"cost_usd": pytest.approx(1.03), "tokens_used": 9100}

    def test_an_exception_without_progress_has_none(self) -> None:
        assert progress_of(RuntimeError("bug")) == {}


class TestUnaffordableTrials:
    def test_a_trial_the_cap_stopped_before_it_began_ends_the_trials(
        self,
        make_context: ContextFactory,
        base_state: EngineState,
        h1_cache: Hypothesis,
        h3_noise: Hypothesis,
        design_scripts: dict[str, ScriptedOutcome],
    ) -> None:
        """
        GIVEN H1 run, then H3 whose first editor request the cap refused
              (TrialUnaffordable: nothing edited or spent)
        WHEN trials runs
        THEN no error: the budget is exhausted (warning and flag, so the
             router combines), H1's trial is the round's only one, and H3
             stays proposed, so no verdict or lesson is ever made for it
        """
        runner = _RaisingRunner(
            StubTrialRunner(design_scripts),
            h3_noise.title,
            TrialUnaffordable("spent 0 USD + estimate 0.48 USD exceeds the cap"),
        )
        nodes = make_nodes(make_context([h1_cache, h3_noise], runner=runner))
        state = _advance(nodes, base_state, _before("trials"))

        delta = nodes["trials"](state)

        assert delta["budget_exhausted"] is True
        (stopped,) = _coded(delta, "budget_exhausted")
        assert stopped.level is EventLevel.warning
        assert stopped.data["not_started"] == 1
        assert "estimate 0.48 USD exceeds the cap" in stopped.message
        assert [t.hypothesis_id for t in _items(delta, "round_trials", Trial)] == [
            h1_cache.id
        ]
        statuses = {h.id: h.status for h in _items(delta, "hypotheses", Hypothesis)}
        assert statuses[h3_noise.id] is HypothesisStatus.proposed
