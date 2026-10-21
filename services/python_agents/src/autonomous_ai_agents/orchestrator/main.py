"""The engine graph and the ``Orchestrator`` that drives it.

``create_graph`` wires the nodes from :mod:`.nodes` into the LangGraph loop
(``langgraph.json`` points at it)::

    START -> connect -> understand -> define -> baseline -> profile -> research
          -> hypotheses -> trials -> judges -> verdicts --(after_verdicts)--+
                 ^                                                         |
                 +--------------------- another round ---------------------+
                                                                           |
         END <- watch <- learn <- deliver <- combine <- approval_gate <----+

``Orchestrator`` always compiles with a checkpointer: without one the
approval gate's ``interrupt()`` ends the run silently and ``Command(resume)``
raises. The checkpointer's serializer is restricted to the engine's own
models and enums (``ENGINE_SERDE_ALLOWLIST``), so a resume gets model
instances back, not plain dicts or strings. The checkpoint store is
code-execution-capable on deserialisation and must never be writable by
trial code.

The checkpoint thread is the source of truth for a run: ``run`` and
``stream`` refuse a run id whose thread already exists, ``resume`` only
continues a thread parked at the approval gate, and a failed result is built
from the last checkpoint, never invented.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Literal, cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.models import (
    ENGINE_SERDE_ALLOWLIST,
    ApprovalDecision,
    ApprovalRequest,
    EngineEvent,
    EventLevel,
    Guardrail,
    Objective,
    Project,
    RunPhase,
    Workload,
)
from autonomous_ai_agents.execution.runner import (
    ScriptedOutcome,
    StubBaselineRunner,
    StubTrialRunner,
)
from autonomous_ai_agents.optimization.judges import default_judges
from autonomous_ai_agents.orchestrator.events import emit, make_event
from autonomous_ai_agents.orchestrator.nodes import (
    LOOP_NODES,
    TAIL_NODES,
    EngineError,
    NodeContext,
    make_nodes,
    make_router,
)
from autonomous_ai_agents.orchestrator.state import EngineState, initial_state
from autonomous_ai_agents.persistence.repository import InMemoryRepository

EngineGraph = CompiledStateGraph[EngineState, None, EngineState, EngineState]
"""The compiled engine graph type."""

RunStatus = Literal["done", "needs_approval", "failed"]

_ROUND_NODES: tuple[str, ...] = LOOP_NODES[LOOP_NODES.index("hypotheses") :]
"""The nodes one round visits: hypotheses, trials, judges, verdicts."""

_FIXED_STEPS = len(LOOP_NODES) - len(_ROUND_NODES) + len(TAIL_NODES)
"""Node visits outside the rounds: six setup nodes and the five tail nodes."""

_SPARE_STEPS = 5
"""Headroom on top of the longest path."""

_PAUSED_AT_GATE: tuple[str, ...] = ("approval_gate",)
"""``StateSnapshot.next`` of a run waiting for the human."""


def run_config(run_id: str, max_rounds: int) -> RunnableConfig:
    """The config that binds a run to its checkpoint thread.

    The recursion limit is the longest path a run with ``max_rounds`` rounds
    can take (``11 + 4 * max_rounds`` node visits) plus five spare steps, so
    a bounded loop never trips LangGraph's recursion guard.
    """
    return {
        "configurable": {"thread_id": run_id},
        "recursion_limit": _FIXED_STEPS + len(_ROUND_NODES) * max_rounds + _SPARE_STEPS,
    }


def _thread(run_id: str) -> RunnableConfig:
    """The config that only names a run's thread (enough for ``get_state``)."""
    return {"configurable": {"thread_id": run_id}}


def build_checkpointer() -> InMemorySaver:
    """An in-memory checkpointer whose serializer allows only engine types."""
    return InMemorySaver(
        serde=JsonPlusSerializer(allowed_msgpack_modules=ENGINE_SERDE_ALLOWLIST)
    )


def default_context() -> NodeContext:
    """Stub runners, the frozen judges and an in-memory repository, no candidates.

    The judges' noise rule uses ``settings.NOISE_MULTIPLIER``. The stub
    baseline measures nothing, so a run on this context stops at the
    baseline until Step 2 provides a real runner.
    """
    return NodeContext(
        runner=StubTrialRunner({}, default=ScriptedOutcome()),
        baseline_runner=StubBaselineRunner(ScriptedOutcome()),
        judges=default_judges(settings.NOISE_MULTIPLIER),
        repository=InMemoryRepository(),
    )


def create_graph(
    checkpointer: BaseCheckpointSaver[str] | None = None,
    *,
    context: NodeContext | None = None,
) -> EngineGraph:
    """Compile the engine loop over ``context`` (default: stubs, no candidates)."""
    ctx = default_context() if context is None else context
    graph: StateGraph[EngineState, None, EngineState, EngineState] = StateGraph(
        EngineState
    )
    for name, node in make_nodes(ctx).items():
        graph.add_node(name, node)
    graph.add_edge(START, LOOP_NODES[0])
    for source, target in pairwise(LOOP_NODES):
        graph.add_edge(source, target)
    graph.add_conditional_edges(
        LOOP_NODES[-1],
        make_router(ctx),
        {
            "approval_gate": "approval_gate",
            "combine": "combine",
            "hypotheses": "hypotheses",
        },
    )
    for source, target in pairwise(TAIL_NODES):
        graph.add_edge(source, target)
    graph.add_edge(TAIL_NODES[-1], END)
    return graph.compile(checkpointer=checkpointer)


@dataclass(frozen=True)
class EngineRunResult:
    """What one ``run`` or ``resume`` call produced."""

    run_id: str
    status: RunStatus
    state: EngineState
    approval_request: ApprovalRequest | None


class Orchestrator:
    """Runs the engine loop for a project, pausing for human approval.

    ``run`` starts a run on its own checkpoint thread (``run_id``); when the
    result is ``needs_approval``, ``resume`` continues the same thread with
    the human's ``ApprovalDecision``. ``stream`` yields the live log instead.
    An ``EngineError`` raised by a node becomes a ``failed`` result whose
    state is the last checkpoint marked failed; any other exception
    propagates. Every result's state (and every streamed run's final state)
    is saved to the context's repository.

    ``run`` and ``stream`` raise ``ValueError`` for a run id whose thread
    already exists; ``resume`` raises ``ValueError`` unless the run is
    paused at the approval gate.
    """

    def __init__(
        self,
        context: NodeContext | None = None,
        checkpointer: BaseCheckpointSaver[str] | None = None,
    ) -> None:
        self.context = default_context() if context is None else context
        self.checkpointer: BaseCheckpointSaver[str] = (
            build_checkpointer() if checkpointer is None else checkpointer
        )
        self.graph: EngineGraph = create_graph(self.checkpointer, context=self.context)

    def run(
        self,
        project: Project,
        workloads: Sequence[Workload],
        objectives: Sequence[Objective],
        guardrails: Sequence[Guardrail],
        *,
        run_id: str | None = None,
        max_rounds: int | None = None,
    ) -> EngineRunResult:
        """Start a run and drive it to completion, approval or failure."""
        state = initial_state(
            project,
            workloads,
            objectives,
            guardrails,
            run_id=run_id,
            max_rounds=max_rounds,
        )
        cfg = run_config(state["run_id"], state["max_rounds"])
        self._refuse_existing(state["run_id"])
        return self._invoke(state["run_id"], cfg, state)

    def resume(self, run_id: str, decision: ApprovalDecision) -> EngineRunResult:
        """Continue a run paused at the approval gate with the human's decision.

        An invalid decision does not fail the run: the result is
        ``needs_approval`` again and its request carries the error.
        """
        snapshot = self.graph.get_state(_thread(run_id))
        if not snapshot.values:
            raise ValueError(f"run {run_id!r} is unknown")
        if snapshot.next != _PAUSED_AT_GATE:
            raise ValueError(f"run {run_id!r} is not waiting for approval")
        cfg = run_config(run_id, snapshot.values["max_rounds"])
        return self._invoke(
            run_id, cfg, Command(resume=decision.model_dump(mode="json"))
        )

    def stream(
        self,
        project: Project,
        workloads: Sequence[Workload],
        objectives: Sequence[Objective],
        guardrails: Sequence[Guardrail],
        *,
        run_id: str | None = None,
        max_rounds: int | None = None,
    ) -> Iterator[EngineEvent]:
        """Start a run and yield its live events as they happen.

        The stream ends with one event of its own after the nodes' events: a
        ``done: N change(s) kept`` event when the run completes, a
        ``paused: N change(s) need approval`` approval-phase event when it
        waits at the gate, or an error-level event when it fails (the run is
        then marked failed). ``resume`` continues a paused run. The final
        state is saved to the repository before that last event is yielded,
        so a consumer that stops at it loses nothing.
        """
        state = initial_state(
            project,
            workloads,
            objectives,
            guardrails,
            run_id=run_id,
            max_rounds=max_rounds,
        )
        run = state["run_id"]
        cfg = run_config(run, state["max_rounds"])
        self._refuse_existing(run)
        try:
            for chunk in self.graph.stream(state, cfg, stream_mode="custom"):
                yield EngineEvent.model_validate(chunk)
        except EngineError as exc:
            failed = self._failed_state(cfg, exc)
            self.context.repository.save_run(failed)
            event = make_event(run, RunPhase.failed, str(exc), level=EventLevel.error)
            emit(event)
            yield event
            return
        snapshot = self.graph.get_state(cfg)
        final = cast(EngineState, dict(snapshot.values))
        self.context.repository.save_run(final)
        if snapshot.next == _PAUSED_AT_GATE:
            pending = len(final["pending_approval_ids"])
            event = make_event(
                run,
                RunPhase.approval,
                f"paused: {pending} change(s) need approval",
                data={"pending": pending},
            )
        else:
            kept = len(final["kept_verdict_ids"])
            event = make_event(
                run, RunPhase.done, f"done: {kept} change(s) kept", data={"kept": kept}
            )
        emit(event)
        yield event

    def _refuse_existing(self, run_id: str) -> None:
        """Raise ``ValueError`` when ``run_id`` already has a checkpoint thread."""
        if self.graph.get_state(_thread(run_id)).values:
            raise ValueError(f"run {run_id!r} already exists")

    def _invoke(
        self,
        run_id: str,
        cfg: RunnableConfig,
        payload: EngineState | Command[str],
    ) -> EngineRunResult:
        try:
            output = self.graph.invoke(payload, cfg, version="v2")
        except EngineError as exc:
            result = EngineRunResult(
                run_id, "failed", self._failed_state(cfg, exc), None
            )
        else:
            if output.interrupts:
                request = ApprovalRequest.model_validate(output.interrupts[0].value)
                result = EngineRunResult(
                    run_id, "needs_approval", output.value, request
                )
            else:
                result = EngineRunResult(run_id, "done", output.value, None)
        self.context.repository.save_run(result.state)
        return result

    def _failed_state(self, cfg: RunnableConfig, exc: EngineError) -> EngineState:
        """The last checkpointed state, marked failed; re-raises without one."""
        values = self.graph.get_state(cfg).values
        if not values:
            raise exc
        state = cast(EngineState, dict(values))
        state["phase"] = RunPhase.failed
        state["error"] = str(exc)
        return state
