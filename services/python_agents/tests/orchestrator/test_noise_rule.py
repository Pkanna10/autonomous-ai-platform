"""The noise rule in the baseline and judges nodes (Step 3, U22; D41 a and c).

Swap points: ``_Calibrator`` stands for ``GitBaselineRunner.calibrate`` (U20),
returning a fixed ``NoiseCalibration``; the A rows a test puts in
``Trial.base_measurements`` stand for ``GitTrialRunner(paired=True)``'s twin
rows (``trial_id`` None, U20). Runners, judges and the repository are the
conftest's stubs and ``default_judges()``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, cast

import pytest

from autonomous_ai_agents.common.errors import EngineError
from autonomous_ai_agents.common.models import (
    METRIC_CPU_TIME_S,
    METRIC_PEAK_RSS_BYTES,
    METRIC_TESTS_PASSED,
    METRIC_WALL_TIME_S,
    Baseline,
    Direction,
    EngineEvent,
    Guardrail,
    Hypothesis,
    JudgeOutcome,
    JudgeResult,
    Measurement,
    NoiseCalibration,
    Objective,
    ObjectiveKind,
    Project,
    RunStats,
    Trial,
    TrialStatus,
    Verdict,
    VerdictOutcome,
    ViolationRule,
    Workload,
)
from autonomous_ai_agents.execution.runner import ScriptedOutcome, StubBaselineRunner
from autonomous_ai_agents.optimization.sources import GenerateResult
from autonomous_ai_agents.orchestrator.nodes import NodeContext, make_nodes
from autonomous_ai_agents.orchestrator.state import EngineState, initial_state

ContextFactory = Callable[..., NodeContext]
COMMIT = "a" * 40
VAL_LOSS = "val_loss"


class _Calibrator:
    """Returns ``result`` and records each call's arguments."""

    def __init__(self, result: NoiseCalibration) -> None:
        self.result = result
        self.calls: list[tuple[tuple[Workload, ...], str, str, int]] = []

    def calibrate(
        self, workloads: Sequence[Workload], *, run_id: str, commit: str, blocks: int
    ) -> NoiseCalibration:
        self.calls.append((tuple(workloads), run_id, commit, blocks))
        return self.result


def _calibration(floor: float, blocks: int = 3) -> NoiseCalibration:
    return NoiseCalibration(blocks=blocks, gaps={"w:wall_time_s": 0.01}, floor=floor)


def _objective(project: Project, metric: str, gain: float) -> Objective:
    kind = ObjectiveKind.peak_memory if "rss" in metric else ObjectiveKind.runtime
    return Objective(
        project_id=project.id,
        kind=kind,
        metric=metric,
        direction=Direction.minimize,
        min_relative_gain=gain,
        description=f"minimize {metric}",
    )


@pytest.fixture
def state(
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
) -> EngineState:
    state = initial_state(
        sample_project,
        [sample_workload],
        [sample_objective],
        sample_guardrails,
        run_id="run-u22",
    )
    state["base_commit"] = COMMIT
    return state


def _baseline(
    make_context: ContextFactory,
    state: EngineState,
    calibration: NoiseCalibration | None = None,
    blocks: int = 3,
    **overrides: Any,
) -> tuple[Baseline, dict[str, object], _Calibrator | None]:
    calibrator = None if calibration is None else _Calibrator(calibration)
    ctx = make_context(calibrator=calibrator, calibration_blocks=blocks, **overrides)
    delta = make_nodes(ctx)["baseline"](state)
    measured = delta["baseline"]
    assert isinstance(measured, Baseline)
    return measured, delta, calibrator


def _first_event(delta: dict[str, object]) -> EngineEvent:
    return cast(list[EngineEvent], delta["events"])[0]


def _gains_of(objectives: Sequence[Objective]) -> dict[str, float]:
    return {o.metric: o.min_relative_gain for o in objectives}


def _gains(baseline: Baseline) -> dict[str, float]:
    return _gains_of(baseline.objectives)


class TestCalibratedFloor:
    def test_the_floor_raises_the_wall_time_objective_and_is_recorded(
        self, make_context: ContextFactory, state: EngineState
    ) -> None:
        measured, delta, calibrator = _baseline(make_context, state, _calibration(0.07))
        assert _gains(measured) == {METRIC_WALL_TIME_S: 0.07}
        assert measured.calibration == _calibration(0.07)
        assert calibrator is not None
        assert calibrator.calls == [(tuple(state["workloads"]), "run-u22", COMMIT, 3)]
        assert set(delta) == {"phase", "baseline", "events"}  # objectives untouched
        assert state["objectives"][0].min_relative_gain == 0.02
        event = _first_event(delta)
        assert event.data["noise_floor"] == 0.07
        assert event.data["calibration_blocks"] == 3
        assert event.data["smallest_provable_gain"] == pytest.approx(0.07)

    def test_a_larger_user_value_stays(
        self, make_context: ContextFactory, state: EngineState
    ) -> None:
        objective = _objective(state["project"], METRIC_WALL_TIME_S, 0.10)
        state["objectives"] = [objective]
        measured, _, _ = _baseline(make_context, state, _calibration(0.05))
        assert _gains(measured) == {METRIC_WALL_TIME_S: 0.10}
        assert measured.objectives[0].id == objective.id

    def test_the_floor_is_never_below_two_percent(
        self, make_context: ContextFactory, state: EngineState
    ) -> None:
        """A calibrator bypassing the model's own bound still yields 2 %; a
        CPU-time objective is not calibrated but gets the 2 % minimum; memory is
        untouched."""
        project = state["project"]
        state["objectives"] = [
            _objective(project, METRIC_WALL_TIME_S, 0.005),
            _objective(project, METRIC_CPU_TIME_S, 0.005),
            _objective(project, METRIC_PEAK_RSS_BYTES, 0.005),
        ]
        state["guardrails"] = []
        loose = NoiseCalibration.model_construct(blocks=3, gaps={}, floor=0.01)
        script = ScriptedOutcome(
            samples={m: (1.0,) * 5 for m in _gains_of(state["objectives"])}
        )
        runner = StubBaselineRunner(script)
        measured, _, _ = _baseline(make_context, state, loose, baseline_runner=runner)
        assert _gains(measured) == {
            METRIC_WALL_TIME_S: 0.02,
            METRIC_CPU_TIME_S: 0.02,
            METRIC_PEAK_RSS_BYTES: 0.005,
        }

    def test_zero_blocks_keeps_step_2(
        self, make_context: ContextFactory, state: EngineState
    ) -> None:
        measured, delta, calibrator = _baseline(
            make_context, state, _calibration(0.07), blocks=0
        )
        assert calibrator is not None and calibrator.calls == []
        assert measured.calibration is None
        assert measured.objectives == tuple(state["objectives"])
        assert "noise_floor" not in _first_event(delta).data

    @pytest.mark.parametrize(
        ("result", "match"),
        [
            (_calibration(0.07, blocks=2), "2 block"),
            (_calibration(1.0), "no gain can be proven"),
        ],
    )
    def test_a_short_or_unprovable_calibration_stops_the_run(
        self,
        make_context: ContextFactory,
        state: EngineState,
        result: NoiseCalibration,
        match: str,
    ) -> None:
        with pytest.raises(EngineError, match=match):
            _baseline(make_context, state, result)

    def test_calibration_needs_the_pinned_commit(
        self, make_context: ContextFactory, state: EngineState
    ) -> None:
        state["base_commit"] = None
        with pytest.raises(EngineError, match="pinned base commit"):
            _baseline(make_context, state, _calibration(0.07))


def _rows(
    workload: Workload,
    trial_id: str | None,
    wall: Sequence[float],
    *,
    val_loss: float | None = 0.5,
) -> tuple[Measurement, ...]:
    """A side's rows: wall time, val_loss (None: dropped) and, on a trial,
    a passing suite; the A rows (``trial_id`` None) carry no suite (U20)."""
    samples = {METRIC_WALL_TIME_S: tuple(wall)}
    if val_loss is not None:
        samples[VAL_LOSS] = (val_loss,) * 5
    if trial_id is not None:
        samples[METRIC_TESTS_PASSED] = (1.0,)
    return tuple(
        Measurement(
            workload_id=workload.id,
            trial_id=trial_id,
            metric=metric,
            stats=RunStats.from_samples(
                values, unit="s" if metric.endswith("_s") else ""
            ),
            samples=values,
        )
        for metric, values in samples.items()
    )


Judged = Callable[..., tuple[Trial, Verdict]]


@pytest.fixture
def judged(
    make_context: ContextFactory, state: EngineState, h1_cache: Hypothesis
) -> Judged:
    """Judge, then verdict, one trial at ``wall`` against the A rows at
    ``base`` (None: unpaired) over the stub baseline (mean 1.80 s);
    ``gain`` replaces the run baseline's min_relative_gain."""
    nodes = make_nodes(make_context())
    measured = nodes["baseline"](state)["baseline"]
    assert isinstance(measured, Baseline)
    state["hypotheses"] = [h1_cache]
    workload = state["workloads"][0]

    def run(
        wall: float,
        base: float | None = None,
        *,
        base_runs: int = 5,
        base_val_loss: float | None = 0.5,
        status: TrialStatus = TrialStatus.measured,
        gain: float = 0.02,
    ) -> tuple[Trial, Verdict]:
        (objective,) = measured.objectives
        raised = objective.model_copy(update={"min_relative_gain": gain})
        state["baseline"] = measured.model_copy(update={"objectives": (raised,)})
        trial = Trial(
            hypothesis_id=h1_cache.id,
            round=1,
            branch="engine/trial-h1",
            status=status,
            error="crashed" if status is TrialStatus.failed else None,
        )
        twin = (
            ()
            if base is None
            else _rows(workload, None, (base,) * base_runs, val_loss=base_val_loss)
        )
        update = {
            "measurements": _rows(workload, trial.id, (wall,) * 5),
            "base_measurements": twin,
        }
        state["round_trials"] = [trial.model_copy(update=update)]
        delta = nodes["judges"](state)
        (out,) = cast(list[Trial], delta["round_trials"])
        state["events"] = cast(list[EngineEvent], delta["events"])
        state["round_trials"] = [out]
        (verdict,) = cast(list[Verdict], nodes["verdicts"](state)["verdicts"])
        return out, verdict

    return run


def _speed(trial: Trial) -> JudgeResult:
    return next(r for r in trial.judge_results if r.metric == METRIC_WALL_TIME_S)


def _base_mean(trial: Trial) -> float:
    """The mean the speed judge compared the trial against."""
    reference = _speed(trial).baseline
    assert reference is not None
    return reference.mean


class TestPairedJudging:
    def test_a_paired_trial_is_judged_against_its_a_rows(
        self, judged: Judged, state: EngineState
    ) -> None:
        """1.08 s is 40 % under the run baseline, 1.8 % under a 1.10 s twin."""
        trial, verdict = judged(1.08, 1.10)
        (event,) = state["events"]
        assert event.message.endswith("judge(s), 1 against a paired base")
        assert event.data["paired"] == 1
        assert _base_mean(trial) == pytest.approx(1.10)
        assert _speed(trial).outcome is JudgeOutcome.inconclusive
        assert verdict.outcome is VerdictOutcome.inconclusive

    def test_paired_judging_applies_the_run_baselines_objectives(
        self, judged: Judged
    ) -> None:
        """1.00 s against a 1.08 s twin is 7.4 %: a keep at 2 %, not at 10 %."""
        trial, verdict = judged(1.00, 1.08)
        assert _speed(trial).gain == pytest.approx(0.08 / 1.08)
        assert verdict.outcome is VerdictOutcome.keep
        assert judged(1.00, 1.08, gain=0.10)[1].outcome is VerdictOutcome.inconclusive

    def test_an_unpaired_trial_is_judged_against_the_run_baseline(
        self, judged: Judged, state: EngineState
    ) -> None:
        trial, verdict = judged(1.08)
        assert "paired" not in state["events"][0].data
        assert _base_mean(trial) == pytest.approx(1.80)
        assert (verdict.outcome, trial.violations) == (VerdictOutcome.keep, ())

    @pytest.mark.parametrize(
        ("broken", "rule"),
        [
            ({"base_val_loss": None}, ViolationRule.missing_measurement),
            ({"base_runs": 3}, ViolationRule.too_few_runs),
        ],
    )
    def test_incomplete_a_rows_reject_the_trial(
        self, judged: Judged, broken: dict[str, Any], rule: ViolationRule
    ) -> None:
        trial, verdict = judged(1.00, 1.80, **broken)
        assert [v.rule for v in trial.violations] == [rule]
        assert trial.violations[0].message.startswith("paired base: ")
        assert verdict.outcome is VerdictOutcome.reject

    def test_a_failed_trial_gets_no_paired_completeness_violations(
        self, judged: Judged
    ) -> None:
        trial, verdict = judged(1.00, 1.80, base_runs=3, status=TrialStatus.failed)
        assert (verdict.outcome, trial.violations) == (VerdictOutcome.reject, ())

    def test_the_guardrail_reads_the_a_rows(self, judged: Judged) -> None:
        """val_loss 0.5 on the trial and the run baseline, 0.40 on the twin:
        25 % worse than the twin, over the 1 % bound."""
        _, verdict = judged(1.00, 1.80, base_val_loss=0.40)
        assert verdict.outcome is VerdictOutcome.reject
        assert "guardrail failed" in verdict.summary

    def test_judging_twice_adds_no_duplicate_violation(
        self, judged: Judged, make_context: ContextFactory, state: EngineState
    ) -> None:
        trial, _ = judged(1.00, 1.80, base_runs=3)
        state["round_trials"] = [trial]
        again = make_nodes(make_context())["judges"](state)
        (rejudged,) = cast(list[Trial], again["round_trials"])
        assert rejudged.violations == trial.violations
        assert len(trial.violations) == 1


class _Generator:
    """Records the objective each request is asked to clear."""

    def __init__(self) -> None:
        self.objectives: list[Objective] = []

    def generate(self, **kwargs: Any) -> GenerateResult:
        self.objectives.append(cast(Objective, kwargs["objective"]))
        return GenerateResult()


def test_the_generator_is_asked_to_clear_the_calibrated_floor(
    make_context: ContextFactory, state: EngineState
) -> None:
    generator = _Generator()
    calibrator = _Calibrator(_calibration(0.07))
    ctx = make_context(calibrator=calibrator, calibration_blocks=3, generator=generator)
    nodes = make_nodes(ctx)
    state["baseline"] = cast(Baseline, nodes["baseline"](state)["baseline"])
    nodes["hypotheses"](state)
    assert [o.min_relative_gain for o in generator.objectives] == [0.07]
