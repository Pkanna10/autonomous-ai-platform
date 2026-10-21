"""End-to-end walking-skeleton scenarios on the compiled engine graph (Step 1).

Seven scenarios from the briefing, run on the raw graph with scripted
runners and asserted on ``GraphOutput.value``:

1. H1 alone -> keep, branch delivery, one lesson, events in loop order.
2. H2 edits a test file -> reject on ``protected_path`` despite passing judges.
3. Two below-noise candidates, one per round -> round 2, report only;
   ``max_rounds=1`` stops after round 1 with a candidate untrialled.
4. H4 (behaviour) -> interrupt with an ``ApprovalRequest``; approve -> delivered.
5. H4 rejected -> report only.
6. A second graph over the same checkpointer resumes the same thread.
7. Without a checkpointer the run still interrupts but cannot resume.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command

from autonomous_ai_agents.common.models import (
    ApprovalDecision,
    Delivery,
    DeliveryKind,
    Guardrail,
    Hypothesis,
    HypothesisStatus,
    JudgeOutcome,
    Objective,
    Project,
    RunPhase,
    Verdict,
    VerdictOutcome,
    ViolationRule,
    Workload,
)
from autonomous_ai_agents.orchestrator.main import (
    EngineGraph,
    build_checkpointer,
    create_graph,
)
from autonomous_ai_agents.orchestrator.nodes import NodeContext
from autonomous_ai_agents.orchestrator.state import EngineState, initial_state

ContextFactory = Callable[..., NodeContext]
GraphFactory = Callable[..., EngineGraph]

LOOP_ORDER: list[RunPhase] = [
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
    RunPhase.combine,
    RunPhase.deliver,
    RunPhase.learn,
    RunPhase.watch,
]


def _config(run_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": run_id}, "recursion_limit": 200}


@pytest.fixture
def start(
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
) -> Callable[..., EngineState]:
    """Return a builder for the initial state of a run."""

    def build(run_id: str, *, max_rounds: int = 3) -> EngineState:
        return initial_state(
            sample_project,
            [sample_workload],
            [sample_objective],
            sample_guardrails,
            run_id=run_id,
            max_rounds=max_rounds,
        )

    return build


def _delivery(state: EngineState) -> Delivery:
    delivery = state["delivery"]
    assert delivery is not None
    return delivery


def _only_verdict(state: EngineState) -> Verdict:
    (verdict,) = state["verdicts"]
    return verdict


# ---------------------------------------------------------------------------
# 1. Clean keep
# ---------------------------------------------------------------------------


def test_h1_is_kept_and_delivered_on_an_engine_branch(
    make_context: ContextFactory,
    engine_graph: GraphFactory,
    start: Callable[..., EngineState],
    sample_project: Project,
    h1_cache: Hypothesis,
) -> None:
    """
    GIVEN H1 (efficiency, 41.7 % faster, tests pass) as the only candidate
    WHEN the graph runs to completion
    THEN the verdict is keep, the delivery is a branch under engine/ that is
         not the default branch, one lesson is saved and the events trace the
         loop in order
    """
    ctx = make_context([h1_cache])
    graph = engine_graph(ctx)
    cfg = _config("e2e-keep")

    output = graph.invoke(start("e2e-keep"), cfg, version="v2")

    assert output.interrupts == ()
    final = output.value
    assert final["phase"] is RunPhase.done
    assert final["error"] is None
    verdict = _only_verdict(final)
    assert verdict.outcome is VerdictOutcome.keep
    assert verdict.hypothesis_id == h1_cache.id
    delivery = _delivery(final)
    assert delivery.kind is DeliveryKind.branch
    assert delivery.branch is not None
    assert delivery.branch.startswith("engine/")
    assert delivery.branch != sample_project.default_branch
    assert delivery.verdict_ids == (verdict.id,)
    assert final["kept_verdict_ids"] == [verdict.id]
    assert len(final["lessons"]) == 1
    assert len(ctx.repository.list_lessons(sample_project.id)) == 1
    assert [event.phase for event in final["events"]] == LOOP_ORDER
    assert final["round"] == 1
    assert [h.status for h in final["hypotheses"]] == [HypothesisStatus.kept]
    assert final["cost_usd"] == pytest.approx(0.12)
    assert final["tokens_used"] == 3400
    assert graph.get_state(cfg).next == ()


# ---------------------------------------------------------------------------
# 2. Protected path beats passing judges
# ---------------------------------------------------------------------------


def test_h2_is_rejected_for_touching_a_test_file(
    make_context: ContextFactory,
    engine_graph: GraphFactory,
    start: Callable[..., EngineState],
    h2_protected: Hypothesis,
) -> None:
    """
    GIVEN H2 (faster, tests pass) that edits tests/test_cache.py
    WHEN the graph runs
    THEN the verdict is reject with a protected_path violation although every
         judge passed, and nothing is delivered
    """
    graph = engine_graph(make_context([h2_protected]))

    final = graph.invoke(
        start("e2e-protected"), _config("e2e-protected"), version="v2"
    ).value

    verdict = _only_verdict(final)
    assert verdict.outcome is VerdictOutcome.reject
    assert [v.rule for v in verdict.violations] == [ViolationRule.protected_path]
    assert verdict.violations[0].path == "tests/test_cache.py"
    assert all(
        r.outcome in (JudgeOutcome.passed, JudgeOutcome.not_applicable)
        for r in verdict.judge_results
    )
    assert _delivery(final).kind is DeliveryKind.report_only
    assert final["phase"] is RunPhase.done


# ---------------------------------------------------------------------------
# 3. Below the noise floor, bounded by rounds
# ---------------------------------------------------------------------------


def test_two_inconclusive_candidates_take_two_rounds(
    make_context: ContextFactory,
    engine_graph: GraphFactory,
    start: Callable[..., EngineState],
    h3_noise: Hypothesis,
) -> None:
    """
    GIVEN two below-noise candidates and one hypothesis per round
    WHEN the graph runs with three rounds allowed
    THEN round 2 is reached, both verdicts are inconclusive and the delivery
         is report only
    """
    twin = h3_noise.model_copy(update={"id": "twin", "title": h3_noise.title})
    graph = engine_graph(make_context([h3_noise, twin], max_hypotheses_per_round=1))

    final = graph.invoke(start("e2e-noise"), _config("e2e-noise"), version="v2").value

    assert final["round"] == 2
    assert [t.round for t in final["trials"]] == [1, 2]
    assert [v.outcome for v in final["verdicts"]] == [VerdictOutcome.inconclusive] * 2
    assert {v.hypothesis_id for v in final["verdicts"]} == {h3_noise.id, twin.id}
    assert _delivery(final).kind is DeliveryKind.report_only
    assert final["phase"] is RunPhase.done
    hypotheses_phases = [e for e in final["events"] if e.phase is RunPhase.hypotheses]
    assert [e.data["round"] for e in hypotheses_phases] == [1, 2]


def test_max_rounds_one_stops_with_a_candidate_untrialled(
    make_context: ContextFactory,
    engine_graph: GraphFactory,
    start: Callable[..., EngineState],
    h3_noise: Hypothesis,
) -> None:
    """
    GIVEN the same two candidates but max_rounds 1
    WHEN the graph runs
    THEN only round 1 happens, the second candidate is never trialled and the
         run still completes with a report
    """
    twin = h3_noise.model_copy(update={"id": "twin", "title": h3_noise.title})
    graph = engine_graph(make_context([h3_noise, twin], max_hypotheses_per_round=1))

    final = graph.invoke(
        start("e2e-rounds", max_rounds=1), _config("e2e-rounds"), version="v2"
    ).value

    assert final["round"] == 1
    assert [t.hypothesis_id for t in final["trials"]] == [h3_noise.id]
    assert len(final["verdicts"]) == 1
    assert _delivery(final).kind is DeliveryKind.report_only
    assert final["phase"] is RunPhase.done


# ---------------------------------------------------------------------------
# 4 and 5. Behaviour change: interrupt, then approve or reject
# ---------------------------------------------------------------------------


def test_h4_interrupts_for_approval_and_is_delivered_once_approved(
    make_context: ContextFactory,
    engine_graph: GraphFactory,
    start: Callable[..., EngineState],
    h4_behaviour: Hypothesis,
) -> None:
    """
    GIVEN H4 (behaviour change, within the val_loss guardrail)
    WHEN the graph runs, pauses, and is resumed with an approval
    THEN the first call returns an interrupt whose item is a behaviour change
         with the graph parked before approval_gate, and the resumed run
         delivers H4's verdict, records the approver and teaches a keep lesson
    """
    ctx = make_context([h4_behaviour])
    graph = engine_graph(ctx)
    cfg = _config("e2e-approve")

    paused = graph.invoke(start("e2e-approve"), cfg, version="v2")

    assert len(paused.interrupts) == 1
    request = paused.interrupts[0].value
    assert request["run_id"] == "e2e-approve"
    assert request["items"][0]["change_class"] == "behaviour"
    assert request["items"][0]["title"] == h4_behaviour.title
    assert graph.get_state(cfg).next == ("approval_gate",)
    verdict_id = request["items"][0]["verdict_id"]
    assert paused.value["pending_approval_ids"] == [verdict_id]
    assert paused.value["delivery"] is None

    decision = ApprovalDecision(
        approved_verdict_ids=(verdict_id,), approver="praveen", note="bf16 is fine"
    )
    resumed = graph.invoke(
        Command(resume=decision.model_dump(mode="json")), cfg, version="v2"
    )

    assert resumed.interrupts == ()
    final = resumed.value
    assert final["phase"] is RunPhase.done
    assert final["pending_approval_ids"] == []
    approval = final["approval"]
    assert approval is not None and approval.approver == "praveen"
    delivery = _delivery(final)
    assert delivery.kind is DeliveryKind.branch
    assert verdict_id in delivery.verdict_ids
    (stored,) = ctx.repository.list_verdicts("e2e-approve")
    assert stored.id == verdict_id
    assert stored.approved_by == "praveen"
    assert stored.approval_note == "bf16 is fine"
    (lesson,) = final["lessons"]
    assert lesson.outcome is VerdictOutcome.keep
    assert [e.phase for e in final["events"]][9:11] == [
        RunPhase.verdicts,
        RunPhase.approval,
    ]
    assert graph.get_state(cfg).next == ()


def test_h4_rejected_at_the_gate_is_reported_only(
    make_context: ContextFactory,
    engine_graph: GraphFactory,
    start: Callable[..., EngineState],
    h4_behaviour: Hypothesis,
) -> None:
    """
    GIVEN a run paused on H4
    WHEN it is resumed with a rejection
    THEN nothing is kept, the delivery is report only and the lesson is reject
    """
    graph = engine_graph(make_context([h4_behaviour]))
    cfg = _config("e2e-reject")
    paused = graph.invoke(start("e2e-reject"), cfg, version="v2")
    verdict_id = paused.interrupts[0].value["items"][0]["verdict_id"]
    decision = ApprovalDecision(rejected_verdict_ids=(verdict_id,), approver="praveen")

    final = graph.invoke(
        Command(resume=decision.model_dump(mode="json")), cfg, version="v2"
    ).value

    assert final["phase"] is RunPhase.done
    assert final["kept_verdict_ids"] == []
    delivery = _delivery(final)
    assert delivery.kind is DeliveryKind.report_only
    assert delivery.verdict_ids == ()
    (lesson,) = final["lessons"]
    assert lesson.outcome is VerdictOutcome.reject


# ---------------------------------------------------------------------------
# 6. Durable resume across graph instances
# ---------------------------------------------------------------------------


def test_a_second_graph_over_the_same_checkpointer_resumes_the_thread(
    make_context: ContextFactory,
    start: Callable[..., EngineState],
    h4_behaviour: Hypothesis,
) -> None:
    """
    GIVEN a run paused on H4 by one graph instance
    WHEN a second graph compiled over the same checkpointer resumes the thread
    THEN the run completes with model instances intact (enum identity holds)
    """
    ctx = make_context([h4_behaviour])
    saver: BaseCheckpointSaver[str] = build_checkpointer()
    cfg = _config("e2e-durable")
    first = create_graph(saver, context=ctx)
    paused = first.invoke(start("e2e-durable"), cfg, version="v2")
    verdict_id = paused.interrupts[0].value["items"][0]["verdict_id"]
    decision = ApprovalDecision(approved_verdict_ids=(verdict_id,), approver="praveen")

    second = create_graph(saver, context=ctx)
    final = second.invoke(
        Command(resume=decision.model_dump(mode="json")), cfg, version="v2"
    ).value

    assert final["phase"] is RunPhase.done
    assert final["run_id"] == "e2e-durable"
    assert isinstance(final["project"], Project)
    assert isinstance(final["delivery"], Delivery)
    assert _delivery(final).verdict_ids == (verdict_id,)
    assert _only_verdict(final).outcome is VerdictOutcome.needs_approval
    assert second.get_state(cfg).next == ()


# ---------------------------------------------------------------------------
# 7. No checkpointer: the gate interrupts but cannot resume
# ---------------------------------------------------------------------------


def test_without_a_checkpointer_the_gate_cannot_resume(
    make_context: ContextFactory,
    start: Callable[..., EngineState],
    h4_behaviour: Hypothesis,
) -> None:
    """
    GIVEN a graph compiled without a checkpointer and H4 as the candidate
    WHEN it runs and a resume is attempted
    THEN the output reports the interrupt and Command(resume) raises RuntimeError
    """
    graph = create_graph(None, context=make_context([h4_behaviour]))

    output = graph.invoke(start("e2e-no-saver"), version="v2")

    assert len(output.interrupts) == 1
    assert output.value["phase"] is RunPhase.verdicts
    with pytest.raises(RuntimeError, match="checkpointer"):
        graph.invoke(Command(resume={"approver": "praveen"}), version="v2")
