"""Tests for the engine graph and the Orchestrator (Step 1, unit U8).

``create_graph`` wires the loop nodes (``langgraph.json`` points at it);
``Orchestrator`` always compiles with a checkpointer so a run can pause at
the approval gate and resume later, and reports every run as an
``EngineRunResult`` with status done, needs_approval or failed.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import FrozenInstanceError
from typing import cast

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import CheckpointTuple
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.models import (
    ENGINE_SERDE_ALLOWLIST,
    METRIC_WALL_TIME_S,
    ApprovalDecision,
    Baseline,
    ChangeClass,
    DeliveryKind,
    EventLevel,
    Guardrail,
    Hypothesis,
    HypothesisStatus,
    Objective,
    Project,
    RunPhase,
    Trial,
    TrialStatus,
    VerdictOutcome,
    Workload,
)
from autonomous_ai_agents.execution.protocols import TrialBrief
from autonomous_ai_agents.execution.runner import (
    ScriptedOutcome,
    StubBaselineRunner,
    StubTrialRunner,
)
from autonomous_ai_agents.optimization.judges import SpeedJudge, default_judges
from autonomous_ai_agents.orchestrator.main import (
    EngineRunResult,
    Orchestrator,
    build_checkpointer,
    create_graph,
    default_context,
    run_config,
)
from autonomous_ai_agents.orchestrator.nodes import (
    LOOP_NODES,
    NODE_NAMES,
    EngineError,
    NodeContext,
)
from autonomous_ai_agents.orchestrator.state import initial_state
from autonomous_ai_agents.persistence.repository import InMemoryRepository

ContextFactory = Callable[..., NodeContext]

LOOP_PHASES: list[RunPhase] = [
    RunPhase.connect,
    RunPhase.understand,
    RunPhase.define,
    RunPhase.baseline,
    RunPhase.profile,
    RunPhase.research,
    RunPhase.hypotheses,
    RunPhase.trials,
    RunPhase.judges,
    RunPhase.verdicts,
]
DELIVERY_PHASES: list[RunPhase] = [
    RunPhase.combine,
    RunPhase.deliver,
    RunPhase.learn,
    RunPhase.watch,
]


# ---------------------------------------------------------------------------
# create_graph
# ---------------------------------------------------------------------------


class TestCreateGraph:
    def test_compiles_every_node_with_the_loop_wiring(self) -> None:
        """
        GIVEN no arguments (the langgraph.json entry point)
        WHEN create_graph is called
        THEN the compiled graph holds every node, the linear chain, the
             three-way routing after verdicts and the delivery tail
        """
        graph = create_graph()

        assert isinstance(graph, CompiledStateGraph)
        assert set(NODE_NAMES) <= set(graph.nodes)
        edges = {(edge.source, edge.target) for edge in graph.get_graph().edges}
        chain = (START, *LOOP_NODES)
        assert all(pair in edges for pair in zip(chain, chain[1:], strict=False))
        assert {("verdicts", "approval_gate"), ("verdicts", "combine")} <= edges
        assert ("verdicts", "hypotheses") in edges
        tail = ("approval_gate", "combine", "deliver", "learn", "watch", END)
        assert all(pair in edges for pair in zip(tail, tail[1:], strict=False))

    def test_the_empty_default_context_stops_at_an_unmeasured_baseline(
        self,
        sample_project: Project,
        sample_workload: Workload,
        sample_objective: Objective,
        sample_guardrails: tuple[Guardrail, ...],
    ) -> None:
        """
        GIVEN the default context (no candidates, a stub baseline that measures
              nothing) compiled without a checkpointer
        WHEN the graph is invoked
        THEN the baseline node refuses to judge against nothing: the
             objective metric was not measured on the workload
        """
        graph = create_graph()
        state = initial_state(
            sample_project, [sample_workload], [sample_objective], sample_guardrails
        )

        with pytest.raises(EngineError, match="missing_measurement"):
            graph.invoke(state, version="v2")
        assert graph.checkpointer is None

    def test_compiles_with_the_given_checkpointer_and_context(
        self, make_context: ContextFactory
    ) -> None:
        """
        GIVEN a checkpointer and a context
        WHEN create_graph is called with them
        THEN the compiled graph uses that checkpointer
        """
        saver = build_checkpointer()

        graph = create_graph(saver, context=make_context())

        assert graph.checkpointer is saver


# ---------------------------------------------------------------------------
# build_checkpointer and default_context
# ---------------------------------------------------------------------------


class TestBuildCheckpointer:
    def test_returns_a_fresh_in_memory_saver_with_the_engine_allowlist(self) -> None:
        """
        GIVEN two calls to build_checkpointer
        WHEN the savers are inspected
        THEN each is a distinct InMemorySaver using a JsonPlusSerializer
        """
        first, second = build_checkpointer(), build_checkpointer()

        assert isinstance(first, InMemorySaver)
        assert first is not second
        assert isinstance(first.serde, JsonPlusSerializer)

    def test_serializer_revives_engine_types_only(
        self, sample_project: Project, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        GIVEN the checkpointer's serializer and a pydantic model that is not
              on the engine allowlist
        WHEN an engine model, an engine enum and the foreign model are dumped
             and loaded back
        THEN the engine model and enum come back as themselves, while the
             foreign model is refused (it comes back as plain data)
        """

        assert Foreign not in ENGINE_SERDE_ALLOWLIST
        serde = build_checkpointer().serde

        def round_trip(value: object) -> object:
            return serde.loads_typed(serde.dumps_typed(value))

        project = round_trip(sample_project)
        phase = round_trip(RunPhase.baseline)
        with caplog.at_level(logging.WARNING):
            foreign = round_trip(Foreign())

        assert isinstance(project, Project) and project == sample_project
        assert phase is RunPhase.baseline
        assert not isinstance(foreign, Foreign)
        assert foreign == {"payload": "not an engine type"}
        # Control: without the allowlist the same model is revived, so the
        # refusal above is the allowlist's doing, not an artefact of the test.
        permissive = JsonPlusSerializer()
        revived = permissive.loads_typed(permissive.dumps_typed(Foreign()))
        assert isinstance(revived, Foreign)


class Foreign(BaseModel):
    """A module-level pydantic model that is deliberately not an engine type."""

    payload: str = "not an engine type"


class TestDefaultContext:
    def test_uses_stub_runners_default_judges_and_an_in_memory_repository(
        self,
    ) -> None:
        """
        GIVEN default_context
        WHEN its fields are inspected
        THEN it carries the stub runners, the frozen judge set and no candidates
        """
        ctx = default_context()

        assert isinstance(ctx.runner, StubTrialRunner)
        assert isinstance(ctx.baseline_runner, StubBaselineRunner)
        assert ctx.judges == default_judges(settings.NOISE_MULTIPLIER)
        assert isinstance(ctx.repository, InMemoryRepository)
        assert ctx.candidates == ()

    def test_judges_take_the_noise_multiplier_from_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        GIVEN NOISE_MULTIPLIER set to 3.0
        WHEN default_context builds the judges
        THEN the gain judges use 3.0 (the knob reaches the noise rule)
        """
        monkeypatch.setattr(settings, "NOISE_MULTIPLIER", 3.0)

        speed = default_context().judges[0]

        assert isinstance(speed, SpeedJudge)
        assert speed.noise_multiplier == 3.0

    def test_default_runner_measures_any_hypothesis(
        self, h1_cache: Hypothesis, sample_workload: Workload
    ) -> None:
        """
        GIVEN the default context's stub runner
        WHEN it runs an unscripted hypothesis
        THEN it returns a measured trial with no measurements (the default script)
        """
        trial = default_context().runner.run(
            h1_cache,
            [sample_workload],
            Baseline(),
            round=1,
            branch="engine/x",
            budget_usd=1.0,
            brief=TrialBrief(understanding=None, hotspots=(), protected=()),
        )

        assert trial.status is TrialStatus.measured
        assert trial.measurements == ()


# ---------------------------------------------------------------------------
# run_config and EngineRunResult
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("max_rounds", [1, 3, 60])
def test_run_config_binds_the_thread_and_sizes_the_recursion_limit(
    max_rounds: int,
) -> None:
    """
    GIVEN a run id and a round budget
    WHEN run_config builds the RunnableConfig
    THEN the thread id is the run id and the recursion limit covers the six
         setup and five tail nodes, four nodes per round and five spare steps
    """
    cfg = run_config("run-7", max_rounds)

    assert cfg["configurable"] == {"thread_id": "run-7"}
    assert cfg["recursion_limit"] == 11 + 4 * max_rounds + 5


def test_engine_run_result_is_frozen(
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
) -> None:
    """
    GIVEN an EngineRunResult
    WHEN a field is assigned
    THEN the assignment is refused
    """
    state = initial_state(
        sample_project, [sample_workload], [sample_objective], sample_guardrails
    )
    result = EngineRunResult(
        run_id=state["run_id"], status="done", state=state, approval_request=None
    )

    with pytest.raises(FrozenInstanceError):
        result.status = "failed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class TestOrchestrator:
    def test_always_compiles_with_a_checkpointer(
        self, make_context: ContextFactory
    ) -> None:
        """
        GIVEN orchestrators built with and without a checkpointer
        WHEN their graphs are inspected
        THEN both have one, and an explicit saver and context are used as given
        """
        saver = build_checkpointer()
        ctx = make_context()

        implicit = Orchestrator()
        explicit = Orchestrator(context=ctx, checkpointer=saver)

        assert implicit.graph.checkpointer is not None
        assert explicit.graph.checkpointer is saver
        assert explicit.context is ctx
        assert implicit.context is not explicit.context

    def test_run_finishes_a_clean_keep(
        self,
        make_context: ContextFactory,
        sample_project: Project,
        sample_workload: Workload,
        sample_objective: Objective,
        sample_guardrails: tuple[Guardrail, ...],
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN H1 as the only candidate
        WHEN the orchestrator runs with an explicit run id
        THEN the result is done, carries the final state, and the run is saved
        """
        ctx = make_context([h1_cache])
        orchestrator = Orchestrator(context=ctx)

        result = orchestrator.run(
            sample_project,
            [sample_workload],
            [sample_objective],
            sample_guardrails,
            run_id="run-keep",
            max_rounds=2,
        )

        assert isinstance(result, EngineRunResult)
        assert result.run_id == "run-keep"
        assert result.status == "done"
        assert result.approval_request is None
        assert result.state["phase"] is RunPhase.done
        assert result.state["max_rounds"] == 2
        (verdict,) = result.state["verdicts"]
        assert verdict.outcome is VerdictOutcome.keep
        delivery = result.state["delivery"]
        assert delivery is not None and delivery.kind is DeliveryKind.branch
        saved = ctx.repository.get_run("run-keep")
        assert saved is not None and saved["phase"] is RunPhase.done

    def test_run_generates_a_uuid_run_id_when_none_is_given(
        self,
        make_context: ContextFactory,
        sample_project: Project,
        sample_workload: Workload,
        sample_objective: Objective,
        sample_guardrails: tuple[Guardrail, ...],
    ) -> None:
        """
        GIVEN no run id
        WHEN the orchestrator runs
        THEN the result's run id is a uuid4 that matches the state's
        """
        result = Orchestrator(context=make_context()).run(
            sample_project, [sample_workload], [sample_objective], sample_guardrails
        )

        assert uuid.UUID(result.run_id).version == 4
        assert result.state["run_id"] == result.run_id

    def test_run_pauses_for_approval_and_resume_delivers(
        self,
        make_context: ContextFactory,
        sample_project: Project,
        sample_workload: Workload,
        sample_objective: Objective,
        sample_guardrails: tuple[Guardrail, ...],
        h4_behaviour: Hypothesis,
    ) -> None:
        """
        GIVEN H4 (a behaviour change) as the only candidate
        WHEN the orchestrator runs and is then resumed with an approval
        THEN the first result needs approval with the request attached and
             the second is done with H4 delivered on a branch
        """
        ctx = make_context([h4_behaviour])
        orchestrator = Orchestrator(context=ctx)

        paused = orchestrator.run(
            sample_project,
            [sample_workload],
            [sample_objective],
            sample_guardrails,
            run_id="run-approve",
        )

        assert paused.status == "needs_approval"
        assert paused.approval_request is not None
        (item,) = paused.approval_request.items
        assert item.change_class is ChangeClass.behaviour
        assert item.title == h4_behaviour.title
        assert paused.state["phase"] is RunPhase.verdicts
        assert paused.state["pending_approval_ids"] == [item.verdict_id]

        resumed = orchestrator.resume(
            "run-approve",
            ApprovalDecision(approved_verdict_ids=(item.verdict_id,), approver="pk"),
        )

        assert resumed.status == "done"
        assert resumed.run_id == "run-approve"
        assert resumed.approval_request is None
        assert resumed.state["phase"] is RunPhase.done
        delivery = resumed.state["delivery"]
        assert delivery is not None
        assert delivery.kind is DeliveryKind.branch
        assert delivery.verdict_ids == (item.verdict_id,)
        approval = resumed.state["approval"]
        assert approval is not None and approval.approver == "pk"

    def test_run_reports_an_engine_error_as_failed(
        self,
        make_context: ContextFactory,
        sample_project: Project,
        sample_workload: Workload,
        sample_objective: Objective,
        sample_guardrails: tuple[Guardrail, ...],
    ) -> None:
        """
        GIVEN a baseline runner that measures too few runs
        WHEN the orchestrator runs
        THEN the result is failed, the state is marked failed with the error
             text, and the events reach the baseline phase
        """
        script = ScriptedOutcome(samples={METRIC_WALL_TIME_S: (1.8, 1.8)})
        ctx = make_context(baseline_runner=StubBaselineRunner(script))

        result = Orchestrator(context=ctx).run(
            sample_project,
            [sample_workload],
            [sample_objective],
            sample_guardrails,
            run_id="run-fail",
        )

        assert result.status == "failed"
        assert result.approval_request is None
        assert result.state["phase"] is RunPhase.failed
        assert result.state["error"] is not None
        assert "2 runs measured" in result.state["error"]
        assert result.state["run_id"] == "run-fail"
        assert [e.phase for e in result.state["events"]] == LOOP_PHASES[:3]
        saved = ctx.repository.get_run("run-fail")
        assert saved is not None and saved["phase"] is RunPhase.failed

    def test_stream_ends_with_an_error_event_on_an_engine_error(
        self,
        make_context: ContextFactory,
        sample_project: Project,
        sample_workload: Workload,
        sample_objective: Objective,
        sample_guardrails: tuple[Guardrail, ...],
    ) -> None:
        """
        GIVEN a baseline runner that measures too few runs
        WHEN the orchestrator streams the run
        THEN the stream ends with one error event and the saved run is failed
        """
        script = ScriptedOutcome(samples={METRIC_WALL_TIME_S: (1.8, 1.8)})
        ctx = make_context(baseline_runner=StubBaselineRunner(script))

        events = list(
            Orchestrator(context=ctx).stream(
                sample_project,
                [sample_workload],
                [sample_objective],
                sample_guardrails,
                run_id="run-stream-fail",
            )
        )

        assert [e.phase for e in events] == [*LOOP_PHASES[:3], RunPhase.failed]
        assert events[-1].level is EventLevel.error
        assert "2 runs measured" in events[-1].message
        saved = ctx.repository.get_run("run-stream-fail")
        assert saved is not None
        assert saved["phase"] is RunPhase.failed
        assert saved["error"] == events[-1].message

    def test_stream_yields_the_live_events_in_loop_order(
        self,
        make_context: ContextFactory,
        sample_project: Project,
        sample_workload: Workload,
        sample_objective: Objective,
        sample_guardrails: tuple[Guardrail, ...],
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN H1 as the only candidate
        WHEN the orchestrator streams the run
        THEN EngineEvents arrive one per node in loop order, tagged with the run id
        """
        orchestrator = Orchestrator(context=make_context([h1_cache]))

        events = list(
            orchestrator.stream(
                sample_project,
                [sample_workload],
                [sample_objective],
                sample_guardrails,
                run_id="run-stream",
            )
        )

        assert [e.phase for e in events] == [
            *LOOP_PHASES,
            *DELIVERY_PHASES,
            RunPhase.done,
        ]
        assert events[-1].message == "done: 1 change(s) kept"
        assert events[-1].data == {"kept": 1}
        assert all(e.run_id == "run-stream" for e in events)
        assert events[0].message == "connected bridge"
        saved = orchestrator.context.repository.get_run("run-stream")
        assert saved is not None
        assert saved["phase"] is RunPhase.done
        delivery = saved["delivery"]
        assert delivery is not None and delivery.branch == "engine/run-run-stream"

    def test_stream_saves_the_run_before_its_last_event(
        self,
        make_context: ContextFactory,
        sample_project: Project,
        sample_workload: Workload,
        sample_objective: Objective,
        sample_guardrails: tuple[Guardrail, ...],
        h1_cache: Hypothesis,
        h4_behaviour: Hypothesis,
    ) -> None:
        """
        GIVEN a consumer that stops reading at the last event
        WHEN a run finishes, and when another pauses at the gate
        THEN both runs are already in the repository at that moment
        """
        for run_id, candidate, last_phase in (
            ("run-break-done", h1_cache, RunPhase.done),
            ("run-break-paused", h4_behaviour, RunPhase.approval),
        ):
            ctx = make_context([candidate])
            orchestrator = Orchestrator(context=ctx)
            seen: list[RunPhase] = []

            for event in orchestrator.stream(
                sample_project,
                [sample_workload],
                [sample_objective],
                sample_guardrails,
                run_id=run_id,
            ):
                seen.append(event.phase)
                if event.phase is last_phase:
                    break

            assert seen[-1] is last_phase, run_id
            assert ctx.repository.get_run(run_id) is not None, run_id

    def test_stream_stops_at_the_gate_and_resume_continues(
        self,
        make_context: ContextFactory,
        sample_project: Project,
        sample_workload: Workload,
        sample_objective: Objective,
        sample_guardrails: tuple[Guardrail, ...],
        h4_behaviour: Hypothesis,
    ) -> None:
        """
        GIVEN H4 as the only candidate
        WHEN the run is streamed and then resumed with an approval
        THEN the stream ends with one paused event after the verdicts event,
             the paused run is saved, and resume finishes the run
        """
        ctx = make_context([h4_behaviour])
        orchestrator = Orchestrator(context=ctx)

        events = list(
            orchestrator.stream(
                sample_project,
                [sample_workload],
                [sample_objective],
                sample_guardrails,
                run_id="run-stream-gate",
            )
        )
        assert [e.phase for e in events] == [*LOOP_PHASES, RunPhase.approval]
        paused_event = events[-1]
        assert paused_event.message == "paused: 1 change(s) need approval"
        assert paused_event.data == {"pending": 1}
        assert paused_event.run_id == "run-stream-gate"
        pending = orchestrator.graph.get_state(run_config("run-stream-gate", 3))
        assert pending.next == ("approval_gate",)
        verdict_id = pending.values["pending_approval_ids"][0]
        saved = ctx.repository.get_run("run-stream-gate")
        assert saved is not None
        assert saved["phase"] is RunPhase.verdicts
        assert saved["pending_approval_ids"] == [verdict_id]

        resumed = orchestrator.resume(
            "run-stream-gate",
            ApprovalDecision(approved_verdict_ids=(verdict_id,), approver="pk"),
        )

        assert resumed.status == "done"
        assert [e.phase for e in resumed.state["events"]] == [
            *LOOP_PHASES,
            RunPhase.approval,
            *DELIVERY_PHASES,
        ]


# ---------------------------------------------------------------------------
# Orchestrator: run ids, resume guards, invalid decisions, recursion budget
# ---------------------------------------------------------------------------


class _ForgetfulSaver(InMemorySaver):
    """Accepts every checkpoint but never returns one (a store that lost the run)."""

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return None


class _WrongRoundRunner:
    """A runner that reports the trial for the next round, not the current one."""

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
        return self._inner.run(
            hypothesis,
            workloads,
            baseline,
            round=round + 1,
            branch=branch,
            budget_usd=budget_usd,
            brief=brief,
        )


class TestOrchestratorGuards:
    @pytest.fixture
    def inputs(
        self,
        sample_project: Project,
        sample_workload: Workload,
        sample_objective: Objective,
        sample_guardrails: tuple[Guardrail, ...],
    ) -> tuple[Project, list[Workload], list[Objective], tuple[Guardrail, ...]]:
        return sample_project, [sample_workload], [sample_objective], sample_guardrails

    def test_run_refuses_a_run_id_that_already_exists(
        self,
        make_context: ContextFactory,
        inputs: tuple[Project, list[Workload], list[Objective], tuple[Guardrail, ...]],
        h1_cache: Hypothesis,
        h3_noise: Hypothesis,
    ) -> None:
        """
        GIVEN a finished run "bridge-nightly"
        WHEN the same orchestrator runs again with that run id
        THEN a ValueError refuses it and nothing more is trialled or saved
        """
        ctx = make_context([h1_cache, h3_noise], max_hypotheses_per_round=2)
        orchestrator = Orchestrator(context=ctx)
        first = orchestrator.run(*inputs, run_id="bridge-nightly")
        assert first.status == "done"
        assert isinstance(ctx.runner, StubTrialRunner)
        calls = list(ctx.runner.calls)

        with pytest.raises(ValueError, match="run 'bridge-nightly' already exists"):
            orchestrator.run(*inputs, run_id="bridge-nightly")

        assert ctx.runner.calls == calls
        saved = ctx.repository.get_run("bridge-nightly")
        assert saved is not None and saved["phase"] is RunPhase.done

    def test_stream_refuses_a_run_id_that_already_exists(
        self,
        make_context: ContextFactory,
        inputs: tuple[Project, list[Workload], list[Objective], tuple[Guardrail, ...]],
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN a run that was started with run()
        WHEN stream() is asked to start the same run id
        THEN a ValueError refuses it before any event is yielded
        """
        orchestrator = Orchestrator(context=make_context([h1_cache]))
        orchestrator.run(*inputs, run_id="run-twice")

        with pytest.raises(ValueError, match="already exists"):
            next(orchestrator.stream(*inputs, run_id="run-twice"))

    @pytest.mark.parametrize("run_id", ["", "../../main", "x y", "run.lock"])
    def test_run_refuses_an_unsafe_run_id(
        self,
        make_context: ContextFactory,
        inputs: tuple[Project, list[Workload], list[Objective], tuple[Guardrail, ...]],
        h1_cache: Hypothesis,
        run_id: str,
    ) -> None:
        """
        GIVEN a run id that cannot name a git branch safely
        WHEN the orchestrator runs with it
        THEN a ValueError refuses it before the graph starts
        """
        ctx = make_context([h1_cache])

        with pytest.raises(ValueError, match="run_id"):
            Orchestrator(context=ctx).run(*inputs, run_id=run_id)
        assert ctx.repository.list_trials(run_id) == ()

    def test_resume_refuses_an_unknown_run(self, make_context: ContextFactory) -> None:
        """
        GIVEN an orchestrator that never ran "never-started"
        WHEN resume is called for it
        THEN a ValueError says the run is unknown
        """
        orchestrator = Orchestrator(context=make_context())

        with pytest.raises(ValueError, match="run 'never-started' is unknown"):
            orchestrator.resume("never-started", ApprovalDecision(approver="pk"))

    def test_resume_refuses_a_finished_run(
        self,
        make_context: ContextFactory,
        inputs: tuple[Project, list[Workload], list[Objective], tuple[Guardrail, ...]],
        h1_cache: Hypothesis,
    ) -> None:
        """
        GIVEN a run that finished with a keep
        WHEN resume is called for it
        THEN a ValueError says it is not waiting for approval
        """
        orchestrator = Orchestrator(context=make_context([h1_cache]))
        assert orchestrator.run(*inputs, run_id="run-done").status == "done"

        with pytest.raises(ValueError, match="not waiting for approval"):
            orchestrator.resume("run-done", ApprovalDecision(approver="pk"))

    def test_resume_refuses_a_failed_run(
        self,
        make_context: ContextFactory,
        inputs: tuple[Project, list[Workload], list[Objective], tuple[Guardrail, ...]],
        h4_behaviour: Hypothesis,
    ) -> None:
        """
        GIVEN a run that failed at the baseline
        WHEN resume is called for it with an approval
        THEN a ValueError says it is not waiting for approval (the failed run
             is not silently re-run past a gate nobody saw)
        """
        script = ScriptedOutcome(samples={METRIC_WALL_TIME_S: (1.8, 1.8)})
        ctx = make_context([h4_behaviour], baseline_runner=StubBaselineRunner(script))
        orchestrator = Orchestrator(context=ctx)
        assert orchestrator.run(*inputs, run_id="run-failed").status == "failed"

        with pytest.raises(ValueError, match="not waiting for approval"):
            orchestrator.resume(
                "run-failed",
                ApprovalDecision(approved_verdict_ids=("whatever",), approver="pk"),
            )
        assert ctx.repository.list_trials("run-failed") == ()

    def test_an_invalid_decision_keeps_the_run_paused_with_the_error(
        self,
        make_context: ContextFactory,
        inputs: tuple[Project, list[Workload], list[Objective], tuple[Guardrail, ...]],
        h4_behaviour: Hypothesis,
    ) -> None:
        """
        GIVEN a run paused on H4
        WHEN resume is called with a decision that bypassed validation, then
             with a valid approval
        THEN the first result still needs approval and its request carries
             the error; the second delivers H4
        """
        ctx = make_context([h4_behaviour])
        orchestrator = Orchestrator(context=ctx)
        paused = orchestrator.run(*inputs, run_id="run-bogus")
        assert paused.approval_request is not None
        verdict_id = paused.approval_request.items[0].verdict_id

        retry = orchestrator.resume(
            "run-bogus",
            # model_construct skips validation, as a tampered client would
            ApprovalDecision.model_construct(approver=cast(str, None)),
        )

        assert retry.status == "needs_approval"
        assert retry.approval_request is not None
        assert retry.approval_request.error is not None
        assert "approver" in retry.approval_request.error
        assert retry.approval_request.items == paused.approval_request.items

        second = orchestrator.resume(
            "run-bogus",
            ApprovalDecision(approved_verdict_ids=("no-such-id",), approver="pk"),
        )
        assert second.status == "needs_approval"
        assert second.approval_request is not None
        assert second.approval_request.error == "unknown verdict ids: no-such-id"

        done = orchestrator.resume(
            "run-bogus",
            ApprovalDecision(approved_verdict_ids=(verdict_id,), approver="pk"),
        )

        assert done.status == "done"
        assert done.state["kept_verdict_ids"] == [verdict_id]
        saved = ctx.repository.get_run("run-bogus")
        assert saved is not None and saved["phase"] is RunPhase.done

    def test_an_engine_error_with_no_checkpoint_propagates(
        self,
        make_context: ContextFactory,
        inputs: tuple[Project, list[Workload], list[Objective], tuple[Guardrail, ...]],
    ) -> None:
        """
        GIVEN a checkpointer that never returns a checkpoint and a baseline
              that fails
        WHEN the orchestrator runs
        THEN the EngineError propagates: no failed state is invented from
             nothing and nothing is saved
        """
        script = ScriptedOutcome(samples={METRIC_WALL_TIME_S: (1.8, 1.8)})
        ctx = make_context(baseline_runner=StubBaselineRunner(script))
        saver = _ForgetfulSaver(
            serde=JsonPlusSerializer(allowed_msgpack_modules=ENGINE_SERDE_ALLOWLIST)
        )
        orchestrator = Orchestrator(context=ctx, checkpointer=saver)

        with pytest.raises(EngineError, match="2 runs measured"):
            orchestrator.run(*inputs, run_id="run-forgotten")
        assert ctx.repository.get_run("run-forgotten") is None

    def test_a_runner_reporting_the_wrong_round_fails_the_run(
        self,
        make_context: ContextFactory,
        inputs: tuple[Project, list[Workload], list[Objective], tuple[Guardrail, ...]],
        h1_cache: Hypothesis,
        design_scripts: dict[str, ScriptedOutcome],
    ) -> None:
        """
        GIVEN a runner whose trial claims the next round
        WHEN the orchestrator runs H1
        THEN the run fails with the runner's inconsistency named, no verdict
        """
        runner = _WrongRoundRunner(StubTrialRunner(design_scripts))
        ctx = make_context([h1_cache], runner=runner)

        result = Orchestrator(context=ctx).run(*inputs, run_id="run-wrong-round")

        assert result.status == "failed"
        assert result.state["error"] is not None
        assert "round is 2, expected 1" in result.state["error"]
        assert result.state["verdicts"] == []

    def test_a_candidate_with_a_stale_status_is_trialled_exactly_once(
        self,
        make_context: ContextFactory,
        inputs: tuple[Project, list[Workload], list[Objective], tuple[Guardrail, ...]],
        h3_noise: Hypothesis,
    ) -> None:
        """
        GIVEN a below-noise candidate that arrives marked inconclusive and a
              below-noise twin, one hypothesis per round
        WHEN the orchestrator runs
        THEN each is trialled exactly once (rounds 1 and 2), each appears once
             in the state's hypotheses, and the run ends after round 2
        """
        stale = h3_noise.model_copy(update={"status": HypothesisStatus.inconclusive})
        twin = h3_noise.model_copy(update={"id": "twin"})
        ctx = make_context([stale, twin], max_hypotheses_per_round=1)

        result = Orchestrator(context=ctx).run(*inputs, run_id="run-stale")

        assert isinstance(ctx.runner, StubTrialRunner)
        assert ctx.runner.calls == [(stale.id, 1), (twin.id, 2)]
        assert [h.id for h in result.state["hypotheses"]] == [stale.id, twin.id]
        assert result.state["round"] == 2
        assert result.status == "done"

    def test_sixty_rounds_without_candidates_complete(
        self,
        make_context: ContextFactory,
        inputs: tuple[Project, list[Workload], list[Objective], tuple[Guardrail, ...]],
    ) -> None:
        """
        GIVEN no candidates and max_rounds 60
        WHEN the orchestrator runs
        THEN the run completes with a report and no trials
        """
        result = Orchestrator(context=make_context()).run(
            *inputs, run_id="run-sixty-empty", max_rounds=60
        )

        assert result.status == "done"
        assert result.state["trials"] == []

    def test_sixty_full_rounds_fit_the_recursion_limit(
        self,
        make_context: ContextFactory,
        inputs: tuple[Project, list[Workload], list[Objective], tuple[Guardrail, ...]],
        h3_noise: Hypothesis,
    ) -> None:
        """
        GIVEN sixty below-noise candidates, one per round, and max_rounds 60
        WHEN the orchestrator runs (6 + 4 x 60 + 5 = 251 node visits)
        THEN every round runs and the run completes without GraphRecursionError
        """
        candidates = [
            h3_noise.model_copy(update={"id": f"noise-{index:02d}"})
            for index in range(60)
        ]
        ctx = make_context(candidates, max_hypotheses_per_round=1)

        result = Orchestrator(context=ctx).run(
            *inputs, run_id="run-sixty-full", max_rounds=60
        )

        assert result.status == "done"
        assert result.state["round"] == 60
        assert len(result.state["verdicts"]) == 60
