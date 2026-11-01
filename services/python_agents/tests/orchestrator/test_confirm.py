"""Confirmation before keep (Step 3, U23; O10, D41 b, D42, D10).

Swap points: ``FakeCombiner`` stands for ``GitCombiner`` (its scripted
``CombineMeasured`` is the confirmation's fresh ABAB re-test, A rows with
``trial_id`` None; ``_NotingCombiner`` adds ``GitCombiner.last_notes``);
``_OutputChanged`` stands for ``EquivalenceJudge`` in
quality mode (it sets ``output_changed``). Runners, the other judges and the
repository are the conftest's stubs and ``default_judges()``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any, cast

import pytest

from autonomous_ai_agents.common.errors import EngineError, RepoTamperedError
from autonomous_ai_agents.common.models import (
    METRIC_TESTS_PASSED,
    METRIC_WALL_TIME_S,
    Baseline,
    ChangeClass,
    EngineEvent,
    EventLevel,
    FrozenFile,
    Guardrail,
    Hypothesis,
    HypothesisStatus,
    JudgeOutcome,
    JudgeResult,
    Measurement,
    Objective,
    Project,
    RunStats,
    Trial,
    TrialStatus,
    Verdict,
    VerdictOutcome,
    Workload,
)
from autonomous_ai_agents.execution.fakes import FakeCombiner
from autonomous_ai_agents.execution.protocols import CombineMeasured, KeptChange
from autonomous_ai_agents.optimization.judges import default_judges
from autonomous_ai_agents.orchestrator.combine_node import (
    COMBINATION_ID,
    CombineRules,
    CombineTarget,
    combine_kept,
    kept_changes,
)
from autonomous_ai_agents.orchestrator.confirm import (
    confirm_one,
    gain_label,
    reported_gain,
)
from autonomous_ai_agents.orchestrator.nodes import (
    NodeContext,
    _combine_rules,
    make_nodes,
)
from autonomous_ai_agents.orchestrator.state import EngineState, initial_state

ContextFactory = Callable[..., NodeContext]
BASE, TRIAL_COMMIT, TIP = "a" * 40, "b" * 40, "c" * 40
VAL_LOSS = "val_loss"
FROZEN = (FrozenFile(path="eval/labels.txt", sha256="d" * 64, size=12),)


class _NotingCombiner(FakeCombiner):
    """A ``FakeCombiner`` with ``GitCombiner``'s ``last_notes``."""

    def __init__(
        self, results: Sequence[CombineMeasured | Exception], notes: tuple[str, ...]
    ) -> None:
        super().__init__(results)
        self.last_notes = notes


@dataclass(frozen=True)
class _OutputChanged:
    """Passes and flags a changed output, on the first look, the second or both."""

    on: tuple[str, ...] = ("first", "second")
    name: str = "output_changed"

    def applies_to(self, objective: Objective) -> bool:
        return True

    def evaluate(self, baseline: Baseline, trial: Trial) -> JudgeResult:
        look = "second" if trial.hypothesis_id == COMBINATION_ID else "first"
        return JudgeResult(
            judge=self.name,
            outcome=JudgeOutcome.passed,
            reason="outputs differ within the quality check",
            output_changed=look in self.on,
        )


def _rows(
    workload: Workload, wall: float, trial_id: str | None, suite: bool
) -> tuple[Measurement, ...]:
    samples: dict[str, tuple[float, ...]] = {
        METRIC_WALL_TIME_S: (wall,) * 5,
        VAL_LOSS: (0.5,) * 5,
    }
    if suite:
        samples[METRIC_TESTS_PASSED] = (1.0,)
    return tuple(
        Measurement(
            workload_id=workload.id,
            trial_id=trial_id,
            metric=metric,
            stats=RunStats.from_samples(values, unit="s"),
            samples=values,
        )
        for metric, values in samples.items()
    )


def _look(workload: Workload, trial: Trial, a: float, b: float) -> CombineMeasured:
    """A fresh one-change re-test: A rows at ``a`` s, B rows (+ suite) at ``b``."""
    return CombineMeasured(
        TIP,
        (trial.id,),
        (),
        _rows(workload, a, None, False),
        _rows(workload, b, None, True),
    )


@pytest.fixture
def state(
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
    make_context: ContextFactory,
) -> EngineState:
    state = initial_state(
        sample_project,
        [sample_workload],
        [sample_objective],
        sample_guardrails,
        run_id="run-u23",
    )
    state["base_commit"] = BASE
    state["baseline"] = cast(
        Baseline, make_nodes(make_context())["baseline"](state)["baseline"]
    )
    return state


def _trial(state: EngineState, hypothesis: Hypothesis, wall: float) -> Trial:
    """``hypothesis``'s measured trial (one id per hypothesis) at ``wall`` s."""
    trial = Trial(
        id=f"t-{hypothesis.id}",
        hypothesis_id=hypothesis.id,
        round=1,
        branch=f"engine/trial-{hypothesis.id}",
        status=TrialStatus.measured,
        commit=TRIAL_COMMIT,
        base_commit=BASE,
    )
    rows = _rows(state["workloads"][0], wall, trial.id, True)
    return trial.model_copy(update={"measurements": rows})


Round = Callable[..., tuple[list[Verdict], dict[str, object], FakeCombiner]]


@pytest.fixture
def run_round(make_context: ContextFactory, state: EngineState) -> Round:
    """Judge then verdict ``trials`` (default: h1 at 1.00 s against the stub
    baseline's 1.80 s); ``looks`` script the combiner; ``ctx`` overrides."""

    def run(
        looks: Sequence[CombineMeasured | Exception] = (),
        *,
        trials: Sequence[tuple[Hypothesis, float]] = (),
        combiner: bool = True,
        notes: tuple[str, ...] = (),
        **ctx: Any,
    ) -> tuple[list[Verdict], dict[str, object], FakeCombiner]:
        fake = _NotingCombiner(looks, notes) if notes else FakeCombiner(looks)
        overrides: dict[str, Any] = {"confirm_winners": True, **ctx}
        context = make_context(combiner=fake if combiner else None, **overrides)
        nodes = make_nodes(context)
        state["hypotheses"] = [h for h, _ in trials]
        state["round_trials"] = [_trial(state, h, wall) for h, wall in trials]
        state["round_trials"] = cast(
            list[Trial], nodes["judges"](state)["round_trials"]
        )
        delta = nodes["verdicts"](state)
        return cast(list[Verdict], delta["verdicts"]), delta, fake

    return run


def _events(delta: dict[str, object]) -> list[EngineEvent]:
    return cast(list[EngineEvent], delta["events"])


def _measured(state: EngineState) -> Baseline:
    measured = state["baseline"]
    assert measured is not None
    return measured


def _verdict(outcome: VerdictOutcome, **fields: Any) -> Verdict:
    defaults: dict[str, Any] = {"trial_id": "t", "hypothesis_id": "h", "gain": 0.4}
    return Verdict(
        outcome=outcome,
        change_class=ChangeClass.efficiency,
        summary=outcome.value,
        **{**defaults, **fields},
    )


class TestConfirmation:
    def test_a_winner_that_confirms_is_kept_with_two_looks(
        self,
        run_round: Round,
        state: EngineState,
        h1_cache: Hypothesis,
        in_memory_repo: Any,
    ) -> None:
        """First look 1.00 vs 1.80 s (44 %); the fresh second look 1.10 vs
        1.80 s (39 %): its own gain is recorded, not the first one's."""
        trial = _trial(state, h1_cache, 1.00)
        look = _look(state["workloads"][0], trial, 1.80, 1.10)
        (verdict,), delta, fake = run_round([look], trials=[(h1_cache, 1.00)])
        assert verdict.outcome is VerdictOutcome.keep
        assert verdict.confirmations == 2
        assert verdict.gain == pytest.approx(0.8 / 1.8)
        assert verdict.confirmed_gain == pytest.approx(0.7 / 1.8)
        assert "confirmed on a second look" in verdict.summary
        (call,) = fake.calls
        (change,) = call.kept
        assert (change.verdict_id, change.commit, call.base_commit) == (
            verdict.id,
            TRIAL_COMMIT,
            BASE,
        )
        assert call.workloads == tuple(state["workloads"])
        assert in_memory_repo.list_verdicts(state["run_id"]) == (verdict,)
        note, summary = _events(delta)
        assert note.data == {"code": "confirmation", "confirmed": 1, "unconfirmed": 0}
        assert summary.data["keep"] == 1

    def test_a_winner_that_does_not_confirm_is_inconclusive(
        self, run_round: Round, state: EngineState, h1_cache: Hypothesis
    ) -> None:
        """The second look is fresh: 1.79 vs 1.80 s fails though the first won."""
        trial = _trial(state, h1_cache, 1.00)
        look = _look(state["workloads"][0], trial, 1.80, 1.79)
        (verdict,), delta, _ = run_round([look], trials=[(h1_cache, 1.00)])
        assert verdict.outcome is VerdictOutcome.inconclusive
        assert verdict.summary.startswith(
            "inconclusive: did not confirm: judge speed inconclusive: "
        )
        assert "inside" in verdict.summary  # the second look's own reason
        assert (verdict.confirmations, verdict.confirmed_gain) == (1, None)
        assert verdict.gain == pytest.approx(0.8 / 1.8)  # the first look's
        assert delta["hypotheses"] == [
            h1_cache.model_copy(update={"status": HypothesisStatus.inconclusive})
        ]
        assert _events(delta)[0].data["unconfirmed"] == 1

    def test_nothing_applied_does_not_confirm(
        self, run_round: Round, h1_cache: Hypothesis
    ) -> None:
        empty = CombineMeasured(BASE, (), (), (), ())
        (verdict,), _, _ = run_round([empty], trials=[(h1_cache, 1.00)])
        assert verdict.outcome is VerdictOutcome.inconclusive
        assert "nothing was applied" in verdict.summary

    def test_a_second_look_with_no_rows_is_no_anti_cheating_reject(
        self, run_round: Round, state: EngineState, h1_cache: Hypothesis
    ) -> None:
        """``GitCombiner`` returns no rows when a workload or the suite fails;
        its notes reach the confirmation note, each once."""
        crashed = CombineMeasured(TIP, (_trial(state, h1_cache, 1.0).id,), (), (), ())
        failed = "the combination was not re-tested: workload w exited 1"
        (verdict,), delta, _ = run_round(
            [crashed], trials=[(h1_cache, 1.00)], notes=(failed, failed)
        )
        assert verdict.outcome is VerdictOutcome.inconclusive
        assert verdict.summary == (
            "inconclusive: did not confirm: the re-test produced no measurements "
            "(a workload or the suite failed on the second look)"
        )
        assert "anti-cheating" not in verdict.summary
        note = _events(delta)[0]
        assert note.message.endswith(f"; combiner notes: {failed}")
        assert note.data["notes"] == failed

    @pytest.mark.parametrize("error", [EngineError("x"), RepoTamperedError("x")])
    def test_a_combiner_error_stops_the_run_and_saves_no_verdict(
        self,
        run_round: Round,
        state: EngineState,
        h1_cache: Hypothesis,
        in_memory_repo: Any,
        error: EngineError,
    ) -> None:
        with pytest.raises(type(error)):
            run_round([error], trials=[(h1_cache, 1.00)])
        assert in_memory_repo.list_verdicts(state["run_id"]) == ()

    def test_the_quality_files_reach_the_combiner_on_both_paths(
        self,
        run_round: Round,
        state: EngineState,
        h1_cache: Hypothesis,
        make_context: ContextFactory,
    ) -> None:
        """The confirmation and the combine re-test score against the
        baseline's frozen files (U24 S3)."""
        state["baseline"] = _measured(state).model_copy(
            update={"quality_files": FROZEN}
        )
        trial = _trial(state, h1_cache, 1.00)
        look = _look(state["workloads"][0], trial, 1.80, 1.10)
        verdicts, _, fake = run_round([look], trials=[(h1_cache, 1.00)])
        state["verdicts"], state["trials"] = verdicts, [trial]
        combiner = FakeCombiner([look])
        make_nodes(make_context(combiner=combiner))["combine"](state)
        calls = [*fake.calls, *combiner.calls]
        assert [call.quality_files for call in calls] == [FROZEN, FROZEN]

    @pytest.mark.parametrize(
        ("floor", "outcome"),
        [(0.02, VerdictOutcome.keep), (0.10, VerdictOutcome.inconclusive)],
    )
    def test_the_second_look_clears_the_raised_floor(
        self,
        run_round: Round,
        state: EngineState,
        h1_cache: Hypothesis,
        floor: float,
        outcome: VerdictOutcome,
    ) -> None:
        """Baseline.objectives carries the floor, state["objectives"] stays
        2 %: a 5.6 % second look holds at 2 %, not at 10 %."""
        (objective,) = _measured(state).objectives
        raised = objective.model_copy(update={"min_relative_gain": floor})
        state["baseline"] = _measured(state).model_copy(
            update={"objectives": (raised,)}
        )
        trial = _trial(state, h1_cache, 1.00)
        look = _look(state["workloads"][0], trial, 1.80, 1.70)
        (verdict,), _, _ = run_round([look], trials=[(h1_cache, 1.00)])
        assert verdict.outcome is outcome
        assert state["objectives"][0].min_relative_gain == 0.02

    def test_a_would_be_review_confirms_as_review(
        self, run_round: Round, state: EngineState, h1_cache: Hypothesis
    ) -> None:
        trial = _trial(state, h1_cache, 1.00)
        look = _look(state["workloads"][0], trial, 1.80, 1.10)
        judges = (*default_judges(), _OutputChanged())
        (verdict,), _, _ = run_round([look], trials=[(h1_cache, 1.00)], judges=judges)
        assert (verdict.outcome, verdict.confirmations) == (VerdictOutcome.review, 2)

    def test_a_keep_whose_second_look_changes_output_does_not_confirm(
        self, run_round: Round, state: EngineState, h1_cache: Hypothesis
    ) -> None:
        """A keep may never stand on a look that saw its output change (D35)."""
        trial = _trial(state, h1_cache, 1.00)
        look = _look(state["workloads"][0], trial, 1.80, 1.10)
        judges = (*default_judges(), _OutputChanged(on=("second",)))
        (verdict,), _, _ = run_round([look], trials=[(h1_cache, 1.00)], judges=judges)
        assert verdict.outcome is VerdictOutcome.inconclusive
        assert verdict.summary.startswith(
            "inconclusive: did not confirm: all judges passed; output changed"
        )

    def test_each_winner_is_re_tested_once_and_nothing_is_charged(
        self,
        run_round: Round,
        state: EngineState,
        h1_cache: Hypothesis,
        h3_noise: Hypothesis,
        h4_behaviour: Hypothesis,
    ) -> None:
        """Two winners, one loser: two one-change looks; no spend in the delta."""
        trials = [(h1_cache, 1.00), (h3_noise, 1.79), (h4_behaviour, 1.20)]
        workload = state["workloads"][0]
        looks = [
            _look(workload, _trial(state, h, 1.0), 1.80, 1.10)
            for h in (h1_cache, h4_behaviour)
        ]
        verdicts, delta, fake = run_round(
            looks, trials=trials, judges=(*default_judges(), _OutputChanged())
        )
        assert [v.confirmations for v in verdicts] == [2, 1, 2]
        assert [len(call.kept) for call in fake.calls] == [1, 1]
        assert not {"cost_usd", "tokens_used"} & set(delta)


class TestStep2Kept:
    def test_confirmation_off_is_step_2(
        self, run_round: Round, h1_cache: Hypothesis
    ) -> None:
        (verdict,), delta, fake = run_round(
            trials=[(h1_cache, 1.00)], confirm_winners=False
        )
        assert (verdict.outcome, verdict.confirmations) == (VerdictOutcome.keep, 1)
        assert (
            verdict.summary
            == "keep: all judges passed; efficiency change ships automatically"
        )
        assert fake.calls == []
        assert len(_events(delta)) == 1

    def test_no_combiner_leaves_a_note_and_one_look(
        self, run_round: Round, h1_cache: Hypothesis
    ) -> None:
        (verdict,), delta, _ = run_round(trials=[(h1_cache, 1.00)], combiner=False)
        assert (verdict.outcome, verdict.confirmations) == (VerdictOutcome.keep, 1)
        note, _ = _events(delta)
        assert note.data == {"code": "confirmation_skipped", "winners": 1}
        assert note.level is EventLevel.warning

    def test_only_winners_are_confirmed(
        self, state: EngineState, make_context: ContextFactory, h1_cache: Hypothesis
    ) -> None:
        verdict = _verdict(VerdictOutcome.reject, hypothesis_id=h1_cache.id)
        rules = _combine_rules(make_context(), _measured(state))
        target = CombineTarget("run-u23", state["project"], BASE, (), "b", 1)
        change = KeptChange("t", h1_cache.id, verdict.id, TRIAL_COMMIT, 0.0, None)
        with pytest.raises(ValueError, match="only a keep or a review"):
            confirm_one(FakeCombiner([]), verdict, change, rules, target)


def test_combine_accepts_review_only_when_asked(
    state: EngineState, make_context: ContextFactory, h1_cache: Hypothesis
) -> None:
    """D10: the review set's combination holds under accept={keep, review}."""
    trial = _trial(state, h1_cache, 1.00)
    verdict = _verdict(
        VerdictOutcome.review, trial_id=trial.id, hypothesis_id=h1_cache.id
    )
    changes = kept_changes([verdict], {trial.id: trial}, {h1_cache.id: h1_cache})
    ctx = make_context(judges=(*default_judges(), _OutputChanged()))
    rules = _combine_rules(ctx, _measured(state))
    target = CombineTarget(
        "run-u23", state["project"], BASE, tuple(state["workloads"]), "b", 1
    )
    look = _look(state["workloads"][0], trial, 1.80, 1.10)
    refused = combine_kept(FakeCombiner([look, look]), changes, rules, target)
    review = frozenset({VerdictOutcome.keep, VerdictOutcome.review})
    held = combine_kept(
        FakeCombiner([look]), changes, replace(rules, accept=review), target
    )
    assert (refused.combination.holds, held.combination.holds) == (False, True)
    assert held.kept_verdict_ids == (verdict.id,)
    assert isinstance(rules, CombineRules) and rules.accept == {VerdictOutcome.keep}


class TestReportedGain:
    @pytest.mark.parametrize(
        ("gain", "label"),
        [(0.049, "small"), (0.05, "solid"), (0.20, "solid"), (0.201, "large")],
    )
    def test_labels(self, gain: float, label: str) -> None:
        assert gain_label(gain) == label

    def test_a_confirmed_gain_is_the_mean_with_half_the_gap_as_margin(self) -> None:
        verdict = _verdict(
            VerdictOutcome.keep, gain=0.22, confirmations=2, confirmed_gain=0.14
        )
        got = reported_gain(verdict, floor=0.02)
        assert got is not None
        assert [got.gain, got.margin] == pytest.approx([0.18, 0.04])
        assert (got.confirmations, got.label) == (2, "solid")
        assert got.text() == "18.0% better, give or take 4.0%, confirmed twice (solid)"
        close = verdict.model_copy(update={"confirmed_gain": 0.21})
        assert reported_gain(close, floor=0.02).margin == 0.02  # type: ignore[union-attr]

    def test_one_look_uses_its_gain_and_the_floor(self) -> None:
        verdict = _verdict(VerdictOutcome.keep, gain=0.049)
        got = reported_gain(verdict, floor=0.03)
        assert got is not None
        assert got.text() == "4.9% better, give or take 3.0%, confirmed once (small)"
        assert (
            reported_gain(verdict.model_copy(update={"gain": None}), floor=0.03) is None
        )
        three = verdict.model_copy(update={"confirmations": 3})
        assert "confirmed 3 times" in reported_gain(three, floor=0.03).text()  # type: ignore[union-attr]
