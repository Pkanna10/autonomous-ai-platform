"""Tests for the engine graph and the Orchestrator (Step 1, unit U8).

``create_graph`` wires the loop nodes (``langgraph.json`` points at it);
``Orchestrator`` always compiles with a checkpointer so a run can pause at
the approval gate and resume later, and reports every run as an
``EngineRunResult`` with status done, needs_approval or failed.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import FrozenInstanceError

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START
from langgraph.graph.state import CompiledStateGraph

from autonomous_ai_agents.common.models import (
    METRIC_WALL_TIME_S,
    ApprovalDecision,
    Baseline,
    ChangeClass,
    DeliveryKind,
    EventLevel,
    Guardrail,
    Hypothesis,
    Objective,
    Project,
    RunPhase,
    TrialStatus,
    VerdictOutcome,
    Workload,
)
from autonomous_ai_agents.execution.runner import (
    ScriptedOutcome,
    StubBaselineRunner,
    StubTrialRunner,
)
from autonomous_ai_agents.optimization.judges import default_judges
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

    def test_without_a_checkpointer_runs_the_empty_default_context(
        self,
        sample_project: Project,
        sample_workload: Workload,
        sample_objective: Objective,
        sample_guardrails: tuple[Guardrail, ...],
    ) -> None:
        """
        GIVEN the default context (no candidates, empty stub measurements)
        WHEN the graph is invoked without a checkpointer
        THEN the run finishes with a report-only delivery and no trials
        """
        graph = create_graph()
        state = initial_state(
            sample_project, [sample_workload], [sample_objective], sample_guardrails
        )

        output = graph.invoke(state, version="v2")

        assert output.interrupts == ()
        assert output.value["phase"] is RunPhase.done
        assert output.value["trials"] == []
        delivery = output.value["delivery"]
        assert delivery is not None
        assert delivery.kind is DeliveryKind.report_only
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
        assert ctx.judges == default_judges()
        assert isinstance(ctx.repository, InMemoryRepository)
        assert ctx.candidates == ()

    def test_default_runner_measures_any_hypothesis(
        self, h1_cache: Hypothesis, sample_workload: Workload
    ) -> None:
        """
        GIVEN the default context's stub runner
        WHEN it runs an unscripted hypothesis
        THEN it returns a measured trial with no measurements (the default script)
        """
        trial = default_context().runner.run(
            h1_cache, [sample_workload], Baseline(), round=1, branch="engine/x"
        )

        assert trial.status is TrialStatus.measured
        assert trial.measurements == ()


# ---------------------------------------------------------------------------
# run_config and EngineRunResult
# ---------------------------------------------------------------------------


def test_run_config_binds_the_thread_to_the_run_id() -> None:
    """
    GIVEN a run id
    WHEN run_config builds the RunnableConfig
    THEN the thread id is the run id and the recursion limit allows every round
    """
    cfg = run_config("run-7")

    assert cfg["configurable"] == {"thread_id": "run-7"}
    assert cfg["recursion_limit"] == 200


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

    def test_resume_with_a_rejection_reports_only(
        self,
        make_context: ContextFactory,
        sample_project: Project,
        sample_workload: Workload,
        sample_objective: Objective,
        sample_guardrails: tuple[Guardrail, ...],
        h4_behaviour: Hypothesis,
    ) -> None:
        """
        GIVEN a run paused on H4
        WHEN it is resumed with a rejection
        THEN the run is done with a report-only delivery and nothing kept
        """
        orchestrator = Orchestrator(context=make_context([h4_behaviour]))
        paused = orchestrator.run(
            sample_project,
            [sample_workload],
            [sample_objective],
            sample_guardrails,
            run_id="run-reject",
        )
        assert paused.approval_request is not None
        verdict_id = paused.approval_request.items[0].verdict_id

        resumed = orchestrator.resume(
            "run-reject",
            ApprovalDecision(rejected_verdict_ids=(verdict_id,), approver="pk"),
        )

        assert resumed.status == "done"
        delivery = resumed.state["delivery"]
        assert delivery is not None and delivery.kind is DeliveryKind.report_only
        assert resumed.state["kept_verdict_ids"] == []

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

    def test_a_state_that_ends_with_an_error_recorded_is_failed(
        self,
        make_context: ContextFactory,
        sample_project: Project,
        sample_workload: Workload,
        sample_objective: Objective,
        sample_guardrails: tuple[Guardrail, ...],
    ) -> None:
        """
        GIVEN an input state whose error field is already set (as a Step 2
              node that records a runner failure instead of raising would)
        WHEN the orchestrator invokes the graph on it
        THEN the run completes but the result status is failed
        """
        orchestrator = Orchestrator(context=make_context())
        state = initial_state(
            sample_project,
            [sample_workload],
            [sample_objective],
            sample_guardrails,
            run_id="run-recorded-error",
        )
        state["error"] = "runner crashed earlier"

        result = orchestrator._invoke("run-recorded-error", state, fallback=state)

        assert result.status == "failed"
        assert result.approval_request is None
        assert result.state["error"] == "runner crashed earlier"
        assert result.state["phase"] is RunPhase.done

    def test_failed_state_falls_back_to_the_input_without_a_checkpoint(
        self,
        make_context: ContextFactory,
        sample_project: Project,
        sample_workload: Workload,
        sample_objective: Objective,
        sample_guardrails: tuple[Guardrail, ...],
    ) -> None:
        """
        GIVEN a run id that was never checkpointed
        WHEN the failed state is built for an error with the input as fallback
        THEN the fallback state comes back marked failed with the error text
        """
        orchestrator = Orchestrator(context=make_context())
        state = initial_state(
            sample_project,
            [sample_workload],
            [sample_objective],
            sample_guardrails,
            run_id="never-run",
        )

        failed = orchestrator._failed_state(
            run_config("never-run"), EngineError("boom"), fallback=state
        )

        assert failed["run_id"] == "never-run"
        assert failed["phase"] is RunPhase.failed
        assert failed["error"] == "boom"
        assert state["phase"] is RunPhase.connect

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

        assert [e.phase for e in events] == [*LOOP_PHASES, *DELIVERY_PHASES]
        assert all(e.run_id == "run-stream" for e in events)
        assert events[0].message == "connected bridge"

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
        THEN the stream ends after the verdicts event and resume finishes the run
        """
        orchestrator = Orchestrator(context=make_context([h4_behaviour]))

        events = list(
            orchestrator.stream(
                sample_project,
                [sample_workload],
                [sample_objective],
                sample_guardrails,
                run_id="run-stream-gate",
            )
        )
        assert [e.phase for e in events] == LOOP_PHASES
        pending = orchestrator.graph.get_state(run_config("run-stream-gate"))
        assert pending.next == ("approval_gate",)
        verdict_id = pending.values["pending_approval_ids"][0]

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
