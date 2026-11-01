"""Review delivery, D38 labels, D42 lines, total time, retry notes (Step 3, U11).

User decision 1 and D10: a behaviour win is a ``review`` verdict that goes to
its own branch, ``engine/review-<run_id>``, with no pause; ``novel`` still
asks. Swap points: ``FakeCombiner`` stands for ``GitCombiner`` (one scripted
``CombineMeasured`` per re-test; ``_NotingCombiner`` adds its ``last_notes``),
``FakePublisher`` for ``GitBranchPublisher`` (it records branch, tip and
base), ``_NotingRunner`` for ``GitTrialRunner``'s ``retry_notes``,
``_Generator`` for ``ClaudeHypothesisGenerator`` and ``_TipChanged`` for
``EquivalenceJudge`` in quality mode. The rest is the conftest's stubs.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast

import pytest
from langgraph.types import Command

from autonomous_ai_agents.common.errors import EngineError
from autonomous_ai_agents.common.models import (
    METRIC_TESTS_PASSED,
    METRIC_WALL_TIME_S,
    ApprovalDecision,
    Baseline,
    BuiltinMeasure,
    ChangeClass,
    Combination,
    Delivery,
    DropUnit,
    EngineEvent,
    FrozenFile,
    Guardrail,
    Hypothesis,
    HypothesisSource,
    HypothesisStatus,
    JudgeOutcome,
    JudgeResult,
    Measurement,
    NoiseCalibration,
    Objective,
    OutputTolerance,
    Project,
    ProjectUnderstanding,
    QualityCheck,
    QualityProposal,
    RunPhase,
    RunStats,
    Trial,
    Verdict,
    VerdictOutcome,
    Violation,
    ViolationRule,
    Workload,
    utc_now,
)
from autonomous_ai_agents.execution.fakes import FakeCombiner, FakePublisher
from autonomous_ai_agents.execution.protocols import CombineMeasured
from autonomous_ai_agents.execution.runner import ScriptedOutcome, StubTrialRunner
from autonomous_ai_agents.optimization.judges import default_judges, derive_verdict
from autonomous_ai_agents.optimization.ranking import lesson_boost
from autonomous_ai_agents.optimization.sources import GenerateResult
from autonomous_ai_agents.orchestrator.main import run_config
from autonomous_ai_agents.orchestrator.nodes import (
    LOOP_NODES,
    NodeContext,
    NodeDelta,
    _change_label,
    _confirmation_notes,
    _dedupe,
    _noise_floor_text,
    _report,
    _review_report,
    _tolerance_text,
    make_nodes,
)
from autonomous_ai_agents.orchestrator.state import REDUCER_KEYS, EngineState
from autonomous_ai_agents.orchestrator.state import initial_state as fresh

ContextFactory = Callable[..., NodeContext]
RUN, BASE, KEEP_TIP, REVIEW_TIP = "run-u11", "a" * 40, "b" * 40, "c" * 40
RUN_BRANCH, REVIEW_BRANCH = f"engine/run-{RUN}", f"engine/review-{RUN}"
FROZEN = (FrozenFile(path="eval/labels.txt", sha256="d" * 64, size=12),)
SENTENCE = (
    f"not merged into {RUN_BRANCH}, never pushed. Not re-tested together with "
    f"{RUN_BRANCH}; merging both is unproven."
)


@dataclass(frozen=True)
class _TipChanged:
    """Passes and flags a changed output on the review re-test's tip only."""

    name: str = "output_changed"

    def applies_to(self, objective: Objective) -> bool:
        return True

    def evaluate(self, baseline: Baseline, trial: Trial) -> JudgeResult:
        changed = trial.commit == REVIEW_TIP
        return JudgeResult(
            judge=self.name,
            outcome=JudgeOutcome.passed,
            reason="ok",
            output_changed=changed,
        )


class _NotingCombiner(FakeCombiner):
    def __init__(self, results: Sequence[CombineMeasured], notes: tuple[str, ...]):
        super().__init__(results)
        self.last_notes = notes


class _NotingRunner(StubTrialRunner):
    """Every trial carries ``note`` in its ``retry_notes``."""

    def __init__(self, scripts: Mapping[str, ScriptedOutcome], note: str) -> None:
        super().__init__(scripts, default=scripts["default"])
        self.note = note

    def run(self, hypothesis: Hypothesis, *args: Any, **kwargs: Any) -> Trial:
        trial = super().run(hypothesis, *args, **kwargs)
        return trial.model_copy(update={"retry_notes": (self.note,)})


class _Generator:
    def __init__(self, idea: Hypothesis) -> None:
        self.idea, self.calls = idea, cast(list[dict[str, Any]], [])

    def generate(self, **kwargs: Any) -> GenerateResult:
        self.calls.append(kwargs)
        return GenerateResult(hypotheses=(self.idea,))


def _apply(state: EngineState, delta: NodeDelta) -> EngineState:
    merged: dict[str, Any] = dict(state)
    for key, value in delta.items():
        merged[key] = (
            [*merged[key], *cast(list[Any], value)] if key in REDUCER_KEYS else value
        )
    return cast(EngineState, merged)


def _rows(workload: str, wall: float, *, suite: bool) -> tuple[Measurement, ...]:
    samples: dict[str, tuple[float, ...]] = {
        METRIC_WALL_TIME_S: (wall,) * 5,
        "val_loss": (0.5,) * 5,
    }
    if suite:
        samples[METRIC_TESTS_PASSED] = (1.0,)
    return tuple(
        Measurement(
            workload_id=workload,
            metric=metric,
            samples=values,
            stats=RunStats.from_samples(values, unit="s"),
        )
        for metric, values in samples.items()
    )


def _look(
    workload: str, applied: Sequence[str], tip: str, wall: float = 1.05
) -> CombineMeasured:
    """A re-test, A at 1.80 s and B at ``wall``: by default it holds when
    something applied."""
    return CombineMeasured(
        tip,
        tuple(applied),
        (),
        _rows(workload, 1.80, suite=False),
        _rows(workload, wall, suite=True),
    )


@pytest.fixture
def start(
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
) -> EngineState:
    return fresh(
        sample_project,
        [sample_workload],
        [sample_objective],
        sample_guardrails,
        run_id=RUN,
        max_rounds=1,
    )


@pytest.fixture
def judged(
    make_context: ContextFactory, start: EngineState
) -> Callable[..., EngineState]:
    """The state after verdicts for ``candidates``, base pinned, trials committed."""

    def run(*candidates: Hypothesis) -> EngineState:
        nodes = make_nodes(make_context(candidates, max_hypotheses_per_round=4))
        state = start
        for name in LOOP_NODES:
            state = _apply(state, nodes[name](state))
        trials = [
            t.model_copy(update={"commit": f"{i + 1:040x}", "diff": f"diff {i}"})
            for i, t in enumerate(state["trials"])
        ]
        return cast(EngineState, {**state, "trials": trials, "base_commit": BASE})

    return run


def _of(state: EngineState, hypothesis: Hypothesis) -> tuple[Trial, Verdict]:
    verdict = next(v for v in state["verdicts"] if v.hypothesis_id == hypothesis.id)
    return next(t for t in state["trials"] if t.id == verdict.trial_id), verdict


def _novel(h4: Hypothesis) -> Hypothesis:
    return h4.model_copy(update={"id": "h5-novel", "change_class": ChangeClass.novel})


def test_a_behaviour_win_is_a_counted_review_never_pending(
    make_context: ContextFactory, start: EngineState, h4_behaviour: Hypothesis
) -> None:
    """
    GIVEN H4, a behaviour change whose judges all pass
    WHEN verdicts runs
    THEN it is review (no staging option left), trialled, counted, not pending
    """
    nodes = make_nodes(make_context([h4_behaviour]))
    state = start
    for name in LOOP_NODES[:-1]:
        state = _apply(state, nodes[name](state))

    delta = nodes["verdicts"](state)

    (verdict,) = cast(list[Verdict], delta["verdicts"])
    assert verdict.outcome is VerdictOutcome.review
    assert "review_behaviour" not in inspect.signature(derive_verdict).parameters
    assert [h.status for h in cast(list[Hypothesis], delta["hypotheses"])] == [
        HypothesisStatus.trialled
    ]
    assert delta["pending_approval_ids"] == []
    (event,) = cast(list[EngineEvent], delta["events"])
    assert event.data["review"] == 1
    assert "0 need approval, 1 to review" in event.message


def test_novel_still_asks_and_review_rides_through_the_gate(
    make_context: ContextFactory,
    engine_graph: Callable[..., Any],
    start: EngineState,
    h4_behaviour: Hypothesis,
) -> None:
    """
    GIVEN H4 (behaviour) and a novel twin in one round, no combiner
    WHEN the graph runs and the novel one is approved on resume
    THEN only the novel one interrupts; the resume raises no KeyError; H4 is
         learned as review and reported as not delivered (nothing re-tested it)
    """
    graph = engine_graph(
        make_context([h4_behaviour, _novel(h4_behaviour)], max_hypotheses_per_round=2)
    )
    cfg = run_config(RUN, 1)

    paused = graph.invoke(start, cfg, version="v2")
    (interrupt,) = paused.interrupts
    (item,) = cast(dict[str, Any], interrupt.value)["items"]
    assert item["change_class"] == "novel"
    decision = ApprovalDecision(
        approved_verdict_ids=(item["verdict_id"],), approver="pk"
    )
    final = graph.invoke(
        Command(resume=decision.model_dump(mode="json")), cfg, version="v2"
    ).value

    lessons = {lesson.hypothesis_id: lesson.outcome for lesson in final["lessons"]}
    assert lessons == {
        h4_behaviour.id: VerdictOutcome.review,
        "h5-novel": VerdictOutcome.keep,
    }
    assert final["review_delivery"] is None
    report = cast(Delivery, final["delivery"]).report_markdown
    assert (
        "- Branch: not created: the review set was not re-tested (no combiner)"
        in report
    )


def test_review_goes_to_its_own_branch_never_the_run_branch(
    make_context: ContextFactory,
    judged: Callable[..., EngineState],
    sample_workload: Workload,
    h1_cache: Hypothesis,
    h4_behaviour: Hypothesis,
) -> None:
    """
    GIVEN a keep (H1) and a review (H4), the review tip's output changed
    WHEN combine and deliver run with a combiner and a publisher
    THEN the review set is re-tested alone (review accepted, quality files
         passed) and published at its own tip on engine/review-<id>; the run
         branch holds H1 only; both reports carry the unproven-merge sentence
    """
    state = judged(h1_cache, h4_behaviour)
    state["baseline"] = cast(Baseline, state["baseline"]).model_copy(
        update={"quality_files": FROZEN}
    )
    (keep_trial, keep), (review_trial, review) = (
        _of(state, h1_cache),
        _of(state, h4_behaviour),
    )
    wid = sample_workload.id
    combiner = FakeCombiner(
        [
            _look(wid, [keep_trial.id], KEEP_TIP),
            _look(wid, [review_trial.id], REVIEW_TIP),
        ]
    )
    publisher = FakePublisher("the diff")
    nodes = make_nodes(
        make_context(
            [h1_cache, h4_behaviour],
            combiner=combiner,
            publisher=publisher,
            judges=(*default_judges(), _TipChanged()),
        )
    )

    state = _apply(state, nodes["combine"](state))
    delta = nodes["deliver"](state)

    first, second = combiner.calls
    assert [c.hypothesis_id for c in first.kept] == [h1_cache.id]
    assert [c.hypothesis_id for c in second.kept] == [h4_behaviour.id]
    assert second.quality_files == FROZEN
    assert state["kept_verdict_ids"] == [keep.id]
    assert [(c.branch, c.tip, c.base) for c in publisher.calls] == [
        (RUN_BRANCH, KEEP_TIP, BASE),
        (REVIEW_BRANCH, REVIEW_TIP, BASE),
    ]
    run_delivery = cast(Delivery, delta["delivery"])
    review_delivery = cast(Delivery, delta["review_delivery"])
    assert run_delivery.verdict_ids == (keep.id,)
    assert (review_delivery.branch, review_delivery.commit) == (
        REVIEW_BRANCH,
        REVIEW_TIP,
    )
    assert review_delivery.verdict_ids == (review.id,)
    lines = review_delivery.report_markdown.splitlines()
    assert [line for line in lines if line.startswith("#")] == [lines[0]]
    assert lines[2] == (
        f"- {h4_behaviour.title}: behaviour change, outputs identical, "
        "16.7% better, give or take 2.0%, confirmed once (solid)"
    )
    for report in (review_delivery.report_markdown, run_delivery.report_markdown):
        assert SENTENCE in report
    assert f"- Branch: {REVIEW_BRANCH} (1 change(s))" in run_delivery.report_markdown
    events = cast(list[EngineEvent], delta["events"])
    assert events[-1].data == {
        "kind": "branch",
        "review": 1,
        "branch": REVIEW_BRANCH,
        "commit": REVIEW_TIP,
    }


def test_a_failed_review_combination_gives_no_branch(
    make_context: ContextFactory,
    judged: Callable[..., EngineState],
    sample_workload: Workload,
    h4_behaviour: Hypothesis,
) -> None:
    """
    GIVEN only a review verdict, and a review re-test that applies it but
          measures no gain (no other change to fall back to)
    WHEN combine and deliver run
    THEN no branch is published and the report says why
    """
    state = judged(h4_behaviour)
    trial, _ = _of(state, h4_behaviour)
    combiner, publisher = (
        FakeCombiner([_look(sample_workload.id, [trial.id], REVIEW_TIP, wall=1.80)]),
        FakePublisher(),
    )
    nodes = make_nodes(
        make_context([h4_behaviour], combiner=combiner, publisher=publisher)
    )

    state = _apply(state, nodes["combine"](state))
    delta = nodes["deliver"](state)

    assert cast(Combination, state["review_combination"]).holds is False
    assert publisher.calls == [] and "review_delivery" not in delta
    report = cast(Delivery, delta["delivery"]).report_markdown
    assert "- Branch: not created: the review re-test did not hold" in report


def test_the_review_branch_holds_only_the_change_the_fallback_kept(
    make_context: ContextFactory,
    judged: Callable[..., EngineState],
    sample_workload: Workload,
    h4_behaviour: Hypothesis,
) -> None:
    """
    GIVEN two review verdicts whose greedy re-test fails, and a fallback that
          holds on the one with the larger gain
    WHEN combine and deliver run
    THEN the review branch delivers that one change only
    """
    twin = h4_behaviour.model_copy(update={"id": "h4-twin"})
    state = judged(h4_behaviour, twin)
    (first, _), (second, best) = _of(state, h4_behaviour), _of(state, twin)
    best = best.model_copy(update={"gain": 0.30})
    state["verdicts"] = [v if v.id != best.id else best for v in state["verdicts"]]
    wid = sample_workload.id
    combiner = FakeCombiner(
        [
            _look(wid, [first.id, second.id], REVIEW_TIP, wall=1.80),
            _look(wid, [second.id], REVIEW_TIP),
        ]
    )
    nodes = make_nodes(
        make_context([h4_behaviour, twin], combiner=combiner, publisher=FakePublisher())
    )

    state = _apply(state, nodes["combine"](state))
    delta = nodes["deliver"](state)

    assert cast(Combination, state["review_combination"]).fallback_trial_id == second.id
    assert cast(Delivery, delta["review_delivery"]).verdict_ids == (best.id,)
    report = cast(Delivery, delta["delivery"]).report_markdown
    assert f"- Branch: {REVIEW_BRANCH} (1 change(s))" in report


@pytest.mark.parametrize("combined", [False, True], ids=["no combiner", "combiner"])
def test_an_approved_novel_change_that_altered_output_is_never_kept(
    make_context: ContextFactory,
    judged: Callable[..., EngineState],
    sample_workload: Workload,
    h1_cache: Hypothesis,
    h4_behaviour: Hypothesis,
    combined: bool,
) -> None:
    """
    GIVEN a keep (H1) and an approved novel change whose output changed
    WHEN combine and deliver run, with or without a combiner
    THEN the novel change is never on the run branch (D35): it joins the
         review set, which reaches engine/review-<id> only when re-tested
    """
    novel = _novel(h4_behaviour)
    state = judged(h1_cache, novel)
    (keep_trial, keep), (novel_trial, asked) = _of(state, h1_cache), _of(state, novel)
    changed = JudgeResult(
        judge="equivalence",
        outcome=JudgeOutcome.passed,
        reason="ok",
        output_changed=True,
    )
    asked = asked.model_copy(update={"judge_results": (*asked.judge_results, changed)})
    state["verdicts"] = [v if v.id != asked.id else asked for v in state["verdicts"]]
    state["approval"] = ApprovalDecision(
        approved_verdict_ids=(asked.id,), approver="pk"
    )
    wid, publisher = sample_workload.id, FakePublisher()
    combiner = FakeCombiner(
        [
            _look(wid, [keep_trial.id], KEEP_TIP),
            _look(wid, [novel_trial.id], REVIEW_TIP),
        ]
    )
    extra: dict[str, Any] = (
        {"combiner": combiner, "publisher": publisher} if combined else {}
    )
    nodes = make_nodes(make_context([h1_cache, novel], **extra))

    state = _apply(state, nodes["combine"](state))
    delta = nodes["deliver"](state)

    assert state["kept_verdict_ids"] == [keep.id]
    run_delivery = cast(Delivery, delta["delivery"])
    assert run_delivery.verdict_ids == (keep.id,)
    assert novel_trial.diff not in run_delivery.combined_diff
    if combined:
        assert [c.hypothesis_id for c in combiner.calls[1].kept] == [novel.id]
        assert [c.branch for c in publisher.calls] == [RUN_BRANCH, REVIEW_BRANCH]
        assert cast(Delivery, delta["review_delivery"]).verdict_ids == (asked.id,)
    else:
        assert "review_delivery" not in delta
        assert "not created: the review set was not re-tested" in (
            run_delivery.report_markdown
        )


def test_a_held_review_combination_without_a_tip_is_refused(
    make_context: ContextFactory,
    judged: Callable[..., EngineState],
    h4_behaviour: Hypothesis,
) -> None:
    """
    GIVEN a review combination recorded as held but with no tip commit
    WHEN deliver runs
    THEN it refuses to publish rather than drop the review set silently
    """
    state = judged(h4_behaviour)
    trial, _ = _of(state, h4_behaviour)
    state["review_combination"] = Combination(
        base_commit=BASE, applied_trial_ids=(trial.id,), holds=True, summary="held"
    )

    with pytest.raises(EngineError, match="review set: it has no tip"):
        make_nodes(make_context([h4_behaviour]))["deliver"](state)


@pytest.mark.parametrize(
    ("tolerance", "text"),
    [
        (
            OutputTolerance(float_digits=12),
            "12 significant digits; counts printed as decimals compared to 12 digits only",
        ),
        (
            OutputTolerance(unordered_lines=True),
            "line order ignored, except an unterminated last line",
        ),
    ],
)
def test_d39_text_for_each_option_alone(tolerance: OutputTolerance, text: str) -> None:
    """GIVEN one tolerance option WHEN described THEN only its clause shows."""
    assert _tolerance_text(tolerance) == f"equal within tolerance ({text})"


def test_without_a_publisher_the_review_delivery_joins_the_diffs(
    make_context: ContextFactory,
    judged: Callable[..., EngineState],
    sample_workload: Workload,
    h4_behaviour: Hypothesis,
) -> None:
    """
    GIVEN a held review combination and no publisher (Step 1 delivery)
    WHEN deliver runs
    THEN the review delivery names the branch, no commit, the trial's diff
    """
    state = judged(h4_behaviour)
    trial, _ = _of(state, h4_behaviour)
    combiner = FakeCombiner([_look(sample_workload.id, [trial.id], REVIEW_TIP)])
    nodes = make_nodes(make_context([h4_behaviour], combiner=combiner))

    state = _apply(state, nodes["combine"](state))
    delivery = cast(Delivery, nodes["deliver"](state)["review_delivery"])

    assert (delivery.branch, delivery.commit, delivery.combined_diff) == (
        REVIEW_BRANCH,
        None,
        trial.diff,
    )


def test_d42_line_per_kept_change_and_the_combination_line(
    judged: Callable[..., EngineState], h1_cache: Hypothesis
) -> None:
    """
    GIVEN a kept H1 confirmed twice (17 % then 19 %) under a raised 3 % floor
          (the primary objective's, D41 c), and a
          held combination re-tested at 25 %
    WHEN the report is written
    THEN the mean, the floor as margin and the label render, and the
         combination's gain is its own line
    """
    state = judged(h1_cache)
    _, verdict = _of(state, h1_cache)
    confirmed = verdict.model_copy(
        update={"gain": 0.17, "confirmed_gain": 0.19, "confirmations": 2}
    )
    baseline = cast(Baseline, state["baseline"])
    raised = tuple(
        o.model_copy(update={"min_relative_gain": 0.03}) for o in baseline.objectives
    )
    state["baseline"] = baseline.model_copy(update={"objectives": raised})
    result = JudgeResult(
        judge="speed",
        outcome=JudgeOutcome.passed,
        reason="ok",
        metric=METRIC_WALL_TIME_S,
        gain=0.25,
    )
    state |= {
        "verdicts": [confirmed],
        "kept_verdict_ids": [verdict.id],
        "combination": Combination(
            base_commit=BASE,
            tip_commit=KEEP_TIP,
            holds=True,
            judge_results=(result,),
            summary="held",
        ),
    }

    report = _report(state, "engine/")

    assert (
        f"- {h1_cache.title}: 18.0% better, give or take 3.0%, confirmed twice (solid)"
        in report
    )
    assert f"- Re-tested together on {RUN_BRANCH}: 25.0% better" in report
    apart = confirmed.model_copy(update={"gain": 0.10, "confirmed_gain": 0.20})
    assert "15.0% better, give or take 5.0%, confirmed twice (solid)" in _report(
        {**state, "verdicts": [apart]}, "engine/"
    )
    bare = cast(Combination, state["combination"]).model_copy(
        update={"judge_results": ()}
    )
    assert "Re-tested together" not in _report(
        {**state, "combination": bare}, "engine/"
    )


ACC = QualityCheck(
    name="accuracy",
    measure=BuiltinMeasure.accuracy,
    labels="eval/l.txt",
    frozen_paths=("eval/l.txt",),
    max_drop=0.005,
)
MAE = QualityCheck(
    name="mae",
    measure=BuiltinMeasure.mae,
    labels="eval/l.txt",
    frozen_paths=("eval/l.txt",),
    max_drop=0.1,
)
REL = ACC.model_copy(update={"drop_unit": DropUnit.relative, "max_drop": 0.01})


@pytest.mark.parametrize(
    ("check", "base", "after", "changed", "head"),
    [
        (
            ACC,
            0.912,
            0.916,
            True,
            "changes results: accuracy 91.2 % → 91.6 % (result improvement)",
        ),
        (ACC, 0.912, 0.912, True, "result kept, output changed"),
        (
            ACC,
            0.912,
            0.909,
            True,
            "result drop within your limit: −0.3 of 0.5 points allowed",
        ),
        (MAE, 0.40, 0.45, True, "result drop within your limit: −0.05 of 0.1 allowed"),
        (ACC, 0.912, 0.912, False, "behaviour change, outputs identical"),
        (REL, 0.9, 0.891, True, "result drop within your limit: −1.0% of 1.0% allowed"),
        (REL, 0.0, 0.1, True, "output changed, no quality number to compare"),
    ],
)
def test_d38_labels(
    check: QualityCheck, base: float, after: float, changed: bool, head: str
) -> None:
    """
    GIVEN a review change with a quality score before and after
    WHEN its label is written
    THEN the result part reads in the metric's unit, then the D42 gain
    """

    def score(value: float) -> Measurement:
        return Measurement(
            workload_id="w",
            metric=check.metric,
            samples=(value,),
            stats=RunStats.from_samples((value,), unit="score"),
        )

    trial = Trial(hypothesis_id="h", round=1, measurements=(score(after),))
    flag = JudgeResult(
        judge="equivalence",
        outcome=JudgeOutcome.passed,
        reason="ok",
        output_changed=changed,
    )
    verdict = Verdict(
        trial_id=trial.id,
        hypothesis_id="h",
        outcome=VerdictOutcome.review,
        change_class=ChangeClass.behaviour,
        judge_results=(flag,),
        gain=0.30,
        confirmed_gain=0.30,
        confirmations=2,
        summary="review",
    )

    wall = score(1.0).model_copy(update={"metric": METRIC_WALL_TIME_S})
    label = _change_label(verdict, trial, (wall, score(base)), check, 0.02)

    assert label == f"{head}, 30.0% better, give or take 2.0%, confirmed twice (large)"


def test_d38_label_reads_the_workload_losing_most() -> None:
    """
    GIVEN accuracy up 5 points on one workload and down 0.3 on another
    WHEN the label is written
    THEN it reports the drop within the limit, never the other's improvement
    """

    def score(workload: str, value: float) -> Measurement:
        return Measurement(
            workload_id=workload,
            metric=ACC.metric,
            samples=(value,),
            stats=RunStats.from_samples((value,), unit="score"),
        )

    trial = Trial(
        hypothesis_id="h",
        round=1,
        measurements=(score("w1", 0.950), score("w2", 0.897)),
    )
    flag = JudgeResult(
        judge="equivalence",
        outcome=JudgeOutcome.passed,
        reason="ok",
        output_changed=True,
    )
    verdict = Verdict(
        trial_id=trial.id,
        hypothesis_id="h",
        outcome=VerdictOutcome.review,
        change_class=ChangeClass.behaviour,
        judge_results=(flag,),
        gain=0.30,
        summary="review",
    )

    label = _change_label(
        verdict, trial, (score("w1", 0.900), score("w2", 0.900)), ACC, 0.02
    )

    assert label.startswith("result drop within your limit: −0.3 of 0.5 points allowed")


def test_d39_sentence_only_when_the_raw_bytes_differ(
    judged: Callable[..., EngineState], h1_cache: Hypothesis
) -> None:
    """
    GIVEN H1 on a workload with a tolerance, kept (main report) or for
          review (review report), raw fingerprints differing from the
          baseline's, equal, or unknown on both sides (runs agreed only within
          the tolerance)
    WHEN each report is written
    THEN the tolerance sentence names the change unless the bytes are equal
    """
    state = judged(h1_cache)
    tolerance = OutputTolerance(float_digits=9, unordered_lines=True)
    state["workloads"] = [
        w.model_copy(update={"output_tolerance": tolerance}) for w in state["workloads"]
    ]
    trial, verdict = _of(state, h1_cache)
    sentence = (
        "equal within tolerance (9 significant digits, line order ignored, except an "
        "unterminated last line; counts printed as decimals compared to 9 digits only)"
    )

    def raw(rows: Sequence[Measurement], digest: str | None) -> tuple[Measurement, ...]:
        return tuple(r.model_copy(update={"raw_fingerprint": digest}) for r in rows)

    baseline = cast(Baseline, state["baseline"])
    held = Combination(
        base_commit=BASE,
        tip_commit=REVIEW_TIP,
        applied_trial_ids=(trial.id,),
        holds=True,
        summary="held",
    )
    review = {
        "verdicts": [verdict.model_copy(update={"outcome": VerdictOutcome.review})],
        "review_combination": held,
    }
    for before, after, shown in (
        ("1" * 64, "2" * 64, True),
        ("1" * 64, "1" * 64, False),
        (None, None, True),
    ):
        state["baseline"] = baseline.model_copy(
            update={"measurements": raw(baseline.measurements, before)}
        )
        moved = trial.model_copy(
            update={"measurements": raw(trial.measurements, after)}
        )
        state["trials"], state["kept_verdict_ids"] = [moved], [verdict.id]
        assert (sentence in _report(state, "engine/")) is shown
        reviewed = _review_report(
            cast(EngineState, {**state, **review}),
            "engine/",
            confirm=False,
            quality=None,
        )
        assert (sentence in reviewed) is shown


def test_total_time_and_retried_trials(
    judged: Callable[..., EngineState], h1_cache: Hypothesis
) -> None:
    """
    GIVEN a run whose first event is 65 min old and one trial retried
    WHEN the report is written
    THEN the total-time line reads 1:05 and counts the retried trial (0:00
         when the clock stepped back)
    """
    state = judged(h1_cache)
    now = utc_now()
    first = state["events"][0].model_copy(
        update={"at": now - timedelta(minutes=65, seconds=10)}
    )
    state["events"] = [first, *state["events"][1:]]
    state["trials"] = [t.model_copy(update={"attempts": 2}) for t in state["trials"]]

    report = _report(state, "engine/", now=now)

    assert (
        "Total time: 1:05, first event to delivery, any approval pause included; "
        "1 trial(s) retried"
    ) in report
    skewed = _report(state, "engine/", now=now - timedelta(hours=2))
    assert "Total time: 0:00," in skewed  # a clock stepped back never goes negative
    assert "Total time: not recorded (no event)" in _report(
        {**state, "events": []}, "engine/"
    )


def test_at_most_three_retry_notes_are_shown(
    judged: Callable[..., EngineState], h1_cache: Hypothesis
) -> None:
    """
    GIVEN a trial with four retry notes
    WHEN the report is written
    THEN three are shown and the fourth is counted
    """
    state = judged(h1_cache)
    notes = ("n1", "n2", "n3", "n4")
    state["trials"] = [
        t.model_copy(update={"retry_notes": notes}) for t in state["trials"]
    ]

    (line,) = [ln for ln in _report(state, "engine/").splitlines() if "n1" in ln]

    assert line.endswith("1 attempt(s)): n1; n2; n3; and 1 more")


def test_retry_notes_reach_the_report_only(
    make_context: ContextFactory,
    engine_graph: Callable[..., Any],
    start: EngineState,
    design_scripts: dict[str, ScriptedOutcome],
    sample_project: Project,
    h3_noise: Hypothesis,
) -> None:
    """
    GIVEN every trial carrying a long retry note, two rounds and a generator
    WHEN the run goes through the loop and delivers
    THEN the note is in the report, capped, and never reaches the generator,
         a trial brief, a verdict or a lesson
    """
    note = "SECRET-NOTE " + "x" * 600
    runner = _NotingRunner(
        {**design_scripts, "default": design_scripts[h3_noise.title]}, note
    )
    idea = Hypothesis(
        project_id=sample_project.id,
        source=HypothesisSource.novel,
        title="g",
        rationale="r",
        change_class=ChangeClass.efficiency,
        expected_gain=0.1,
        provability=0.5,
        risk=0.1,
    )
    generator = _Generator(idea)
    graph = engine_graph(make_context([h3_noise], runner=runner, generator=generator))
    final = graph.invoke(
        {**start, "max_rounds": 2}, run_config(RUN, 2), version="v2"
    ).value

    assert generator.calls and len(final["trials"]) == 2
    report = cast(Delivery, final["delivery"]).report_markdown
    lines = [ln for ln in report.splitlines() if "SECRET-NOTE" in ln]
    assert [ln.startswith(f"- {h3_noise.title} (trial ") for ln in lines[:1]] == [True]
    assert len(lines) == 2 and all(len(ln) < 300 for ln in lines)
    for leaked in (generator.calls, runner.briefs, final["verdicts"], final["lessons"]):
        assert "SECRET-NOTE" not in repr(leaked)


def test_noise_floor_names_the_calibration_and_the_confirmation(
    judged: Callable[..., EngineState], h1_cache: Hypothesis
) -> None:
    """
    GIVEN a baseline with and without a calibration
    WHEN the Noise floor line is written with confirmation off and on
    THEN it names the blocks and the floor, and the confirmation setting
    """
    state = judged(h1_cache)
    baseline = cast(Baseline, state["baseline"])
    calibrated = baseline.model_copy(
        update={"calibration": NoiseCalibration(blocks=3, gaps={"w": 0.01}, floor=0.03)}
    )

    off = _noise_floor_text({**state, "baseline": calibrated}, confirm=False)
    on = _noise_floor_text(state, confirm=True)

    assert off.endswith(
        "; calibrated over 3 A/A block(s): project floor 3.0%, largest gap 1.0%; confirmation off"
    )
    assert on.endswith("; not calibrated; winners confirmed on a second look")


def test_combiner_notes_are_capped_in_events_and_report(
    make_context: ContextFactory,
    judged: Callable[..., EngineState],
    sample_workload: Workload,
    h1_cache: Hypothesis,
) -> None:
    """
    GIVEN a combiner whose notes run to thousands of characters
    WHEN combine, the confirmation note and the report carry them
    THEN each is cut to the cap with an ellipsis
    """
    state = judged(h1_cache)
    trial, verdict = _of(state, h1_cache)
    combiner = _NotingCombiner(
        [_look(sample_workload.id, [trial.id], KEEP_TIP)], ("n" * 3000,)
    )
    nodes = make_nodes(make_context([h1_cache], combiner=combiner))

    delta = nodes["combine"](state)
    (looked,) = _confirmation_notes(state, [verdict], True, ["m" * 3000])
    report = _report(_apply(state, delta), "engine/")

    noted = next(
        e
        for e in cast(list[EngineEvent], delta["events"])
        if e.data.get("code") == "combiner_notes"
    )
    for text in (str(noted.data["notes"]), str(looked.data["notes"])):
        assert len(text) == 500 and text.endswith("…")
    (line,) = [ln for ln in report.splitlines() if ln.startswith("- Combiner notes: ")]
    assert len(line) < 560


def test_quality_files_parked_ideas_and_a_proposal_are_reported(
    judged: Callable[..., EngineState], h1_cache: Hypothesis, h3_noise: Hypothesis
) -> None:
    """
    GIVEN frozen quality files, a parked idea and a quality proposal
    WHEN the report is written
    THEN each is listed, the proposal as not active
    """
    state = judged(h1_cache)
    state["baseline"] = cast(Baseline, state["baseline"]).model_copy(
        update={"quality_files": FROZEN}
    )
    state["parked"] = [h3_noise.model_copy(update={"parked_reason": "needs approval"})]
    proposal = QualityProposal(
        measure=BuiltinMeasure.accuracy, labels="eval/labels.txt"
    )
    state["understanding"] = ProjectUnderstanding(
        language="python", summary="s", served_by_model="m", quality_proposal=proposal
    )

    report = _report(state, "engine/")

    assert f"- Quality files: eval/labels.txt sha256 {'d' * 64} (12 bytes)" in report
    assert f"- {h3_noise.title}: needs approval" in report
    assert (
        "- Suggested quality check (not active): accuracy over eval/labels.txt"
        in report
    )


def test_dedupe_keeps_each_measurement_message() -> None:
    """
    GIVEN two missing_measurement and two too_few_runs messages (one repeated)
          and a protected path reported twice with different words
    WHEN deduplicated
    THEN every distinct measurement message stays; the path is reported once
    """

    def v(rule: ViolationRule, message: str, path: str | None = None) -> Violation:
        return Violation(rule=rule, message=message, path=path)

    missing, few, protected = (
        ViolationRule.missing_measurement,
        ViolationRule.too_few_runs,
        ViolationRule.protected_path,
    )
    found = [
        v(missing, "a"),
        v(missing, "b"),
        v(missing, "a"),
        v(few, "c"),
        v(few, "d"),
        v(protected, "x", "t.py"),
        v(protected, "y", "t.py"),
    ]

    assert [x.message for x in _dedupe(found)] == ["a", "b", "c", "d", "x"]


def test_review_lessons_are_neutral_and_a_confirmed_gain_is_the_mean(
    make_context: ContextFactory,
    judged: Callable[..., EngineState],
    h1_cache: Hypothesis,
    h4_behaviour: Hypothesis,
) -> None:
    """
    GIVEN a keep confirmed at 17 % then 19 % and an unconfirmed review
    WHEN learn runs
    THEN the keep's lesson gain is 18 % (D42's two-look mean) and the review
         lesson is recorded as review, neutral in ranking
    """
    state = judged(h1_cache, h4_behaviour)
    _, keep = _of(state, h1_cache)
    confirmed = keep.model_copy(
        update={"gain": 0.17, "confirmed_gain": 0.19, "confirmations": 2}
    )
    state["verdicts"] = [confirmed, _of(state, h4_behaviour)[1]]

    delta = make_nodes(make_context())["learn"](state)

    by_hypothesis = {
        lesson.hypothesis_id: lesson for lesson in cast(list[Any], delta["lessons"])
    }
    assert by_hypothesis[h1_cache.id].gain == pytest.approx(0.18)
    assert by_hypothesis[h1_cache.id].text.endswith("keep (+18.0%)")
    review = by_hypothesis[h4_behaviour.id]
    assert review.outcome is VerdictOutcome.review
    assert lesson_boost(h4_behaviour, [review]) == 0.0
    assert state["phase"] is RunPhase.verdicts
