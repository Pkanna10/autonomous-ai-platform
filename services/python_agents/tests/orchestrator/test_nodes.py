"""Tests for the engine loop nodes (Step 1, unit U7).

Every node is a closure over a ``NodeContext`` (``make_nodes``) that takes
the state and returns only its delta: the keys it changes, plus one event,
and for the append-only channels (``REDUCER_KEYS``) only the new items. The
tests below drive the nodes through a tiny merger that mimics LangGraph's
reducers, so no graph is involved except for ``approval_gate``, whose
``interrupt()`` needs a running graph.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import FrozenInstanceError, replace
from typing import Any, TypeVar, cast

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.models import (
    METRIC_PEAK_RSS_BYTES,
    METRIC_WALL_TIME_S,
    ApprovalDecision,
    ApprovalRequest,
    Baseline,
    ChangeClass,
    Delivery,
    DeliveryKind,
    Direction,
    EngineEvent,
    EventLevel,
    Guardrail,
    Hotspot,
    Hypothesis,
    HypothesisStatus,
    JudgeOutcome,
    JudgeResult,
    Lesson,
    Measurement,
    Objective,
    ObjectiveKind,
    Project,
    RunPhase,
    RunStats,
    Technique,
    Trial,
    TrialStatus,
    Verdict,
    VerdictOutcome,
    ViolationRule,
    Workload,
)
from autonomous_ai_agents.execution.runner import (
    ScriptedOutcome,
    StubBaselineRunner,
    StubTrialRunner,
)
from autonomous_ai_agents.optimization.anticheat import DEFAULT_PROTECTED_PATTERNS
from autonomous_ai_agents.orchestrator.main import build_checkpointer, run_config
from autonomous_ai_agents.orchestrator.nodes import (
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
    ) -> Trial:
        trial = self._inner.run(
            hypothesis, workloads, baseline, round=round, branch=branch
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
    ) -> Trial:
        trial = self._inner.run(
            hypothesis, workloads, baseline, round=round, branch=branch
        )
        fast = tuple(
            _measurement(m.workload_id, m.metric, (1.0,) * 5)
            for m in trial.measurements
            if m.metric == METRIC_WALL_TIME_S
        )
        return trial.model_copy(update={"measurements": (*fast, *trial.measurements)})


class _DoublingBaselineRunner:
    """A baseline runner that reports every measurement twice."""

    def __init__(self, inner: StubBaselineRunner) -> None:
        self._inner = inner

    def measure(self, workloads: Sequence[Workload]) -> tuple[Measurement, ...]:
        measured = self._inner.measure(workloads)
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
        THEN the baseline carries measurements, objectives and guardrails
             and the event reports n and the primary metric's mean
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
        event = _only_event(delta)
        assert event.data["metric"] == METRIC_WALL_TIME_S
        assert event.data["n"] == 5
        assert event.data["mean"] == pytest.approx(1.80)

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
            f"{METRIC_WALL_TIME_S} was not measured on workload {sample_workload.id}"
        )

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
        WHEN the graph resumes with a decision that names no pending verdict
        THEN the repository verdict still needs approval and the hypothesis
             keeps its trialled status
        """
        ctx, nodes, state = pending_state
        graph = _single_node_graph(nodes["approval_gate"], "approval_gate")
        cfg = run_config(RUN_ID, 3)
        graph.invoke(state, cfg, version="v2")
        before = ctx.repository.list_verdicts(RUN_ID)
        decision = ApprovalDecision(approved_verdict_ids=("unknown",), approver="pk")

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
        (row,) = [line for line in lines if line.startswith(f"| {h1_cache.title} |")]
        assert row.endswith(
            "| reject | n/a | reject: trial failed: boom \\| ## Approved by security "
            "team &lt;img src=https://attacker.example/x?k=1&gt; \\[merge now\\]"
            "(https://attacker.example) \\`rm -rf\\` &amp; \\\\\\| done |"
        )

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
            summary=str(outcome),
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
        assert decided[2].summary == "approved by pk: " + yes.summary
        assert decided[3].summary == "rejected by pk: " + no.summary


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
