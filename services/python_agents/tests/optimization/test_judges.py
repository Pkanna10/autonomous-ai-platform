"""Tests for the judges and verdict derivation (Step 1, unit U6).

Judges are frozen evaluators over measurements already on a trial: they pair
baseline and trial measurements per workload, apply the noise rule, the
fingerprint rule and the guardrail bounds, and never touch state. The verdict
is a pure, ordered derivation over judge results and anti-cheating violations.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import FrozenInstanceError

import pytest

from autonomous_ai_agents.common.models import (
    METRIC_PEAK_RSS_BYTES,
    METRIC_TESTS_PASSED,
    METRIC_THROUGHPUT_PER_S,
    METRIC_WALL_TIME_S,
    Baseline,
    ChangeClass,
    Direction,
    Guardrail,
    GuardrailKind,
    Hypothesis,
    HypothesisSource,
    JudgeOutcome,
    JudgeResult,
    Measurement,
    Objective,
    ObjectiveKind,
    RunStats,
    Trial,
    TrialStatus,
    Verdict,
    VerdictOutcome,
    Violation,
    ViolationRule,
)
from autonomous_ai_agents.optimization.anticheat import check_diff_all, fingerprint
from autonomous_ai_agents.optimization.judges import (
    EquivalenceJudge,
    GuardrailMetricJudge,
    Judge,
    MemoryJudge,
    MetricGainJudge,
    SpeedJudge,
    default_judges,
    derive_verdict,
    primary_metric,
)

# Imported under an alias: a module-level name starting with "Test" would be
# collected by pytest as a test class.
from autonomous_ai_agents.optimization.judges import TestSuiteJudge as SuiteJudge

PROJECT = "project-1"
W1 = "w1"
W2 = "w2"
W3 = "w3"
VAL_LOSS = "val_loss"
ACCURACY = "accuracy"


# ---------------------------------------------------------------------------
# Fixture builders (hand-built models, no I/O)
# ---------------------------------------------------------------------------


def _stats(mean: float, stdev: float = 0.03, unit: str = "s") -> RunStats:
    return RunStats(
        n=5, mean=mean, stdev=stdev, min=mean - stdev, max=mean + stdev, unit=unit
    )


def _measurement(
    workload_id: str,
    metric: str,
    mean: float,
    stdev: float = 0.03,
    *,
    unit: str = "s",
    digest: str | None = None,
) -> Measurement:
    return Measurement(
        workload_id=workload_id,
        metric=metric,
        stats=_stats(mean, stdev, unit),
        samples=(mean,) * 5,
        output_fingerprint=digest,
    )


def _objective(
    metric: str = METRIC_WALL_TIME_S,
    direction: Direction = Direction.minimize,
    *,
    kind: ObjectiveKind = ObjectiveKind.runtime,
    min_relative_gain: float = 0.02,
    weight: float = 1.0,
) -> Objective:
    return Objective(
        project_id=PROJECT,
        kind=kind,
        metric=metric,
        direction=direction,
        min_relative_gain=min_relative_gain,
        weight=weight,
        description=f"{direction} {metric}",
    )


def _guardrail(
    kind: GuardrailKind,
    *,
    metric: str | None = None,
    max_drop: float | None = None,
    direction: Direction | None = None,
) -> Guardrail:
    return Guardrail(
        project_id=PROJECT,
        kind=kind,
        metric=metric,
        max_drop=max_drop,
        direction=direction,
        description=str(kind),
    )


def _bound(
    metric: str, max_drop: float, direction: Direction = Direction.minimize
) -> Guardrail:
    return _guardrail(
        GuardrailKind.metric_bound,
        metric=metric,
        max_drop=max_drop,
        direction=direction,
    )


def _baseline(
    *measurements: Measurement,
    objectives: Sequence[Objective] = (),
    guardrails: Sequence[Guardrail] = (),
) -> Baseline:
    return Baseline(
        measurements=measurements,
        objectives=tuple(objectives),
        guardrails=tuple(guardrails),
    )


def _trial(
    *measurements: Measurement,
    status: TrialStatus = TrialStatus.measured,
    touched_paths: Sequence[str] = ("src/bridge/encoder.py",),
    error: str | None = None,
) -> Trial:
    return Trial(
        hypothesis_id="h1",
        round=1,
        status=status,
        touched_paths=tuple(touched_paths),
        measurements=measurements,
        error=error,
    )


def _hypothesis(change_class: ChangeClass = ChangeClass.efficiency) -> Hypothesis:
    return Hypothesis(
        project_id=PROJECT,
        source=HypothesisSource.playbook,
        title="cache frozen-encoder embeddings",
        rationale="the encoder is frozen and re-run every epoch",
        change_class=change_class,
        expected_gain=0.4,
        provability=0.9,
        risk=0.1,
    )


def _result(
    judge: str,
    outcome: JudgeOutcome,
    *,
    metric: str | None = None,
    gain: float | None = None,
) -> JudgeResult:
    return JudgeResult(
        judge=judge,
        outcome=outcome,
        metric=metric,
        gain=gain,
        reason=f"{judge} {outcome}",
    )


def _violation() -> Violation:
    return Violation(
        rule=ViolationRule.protected_path,
        path="tests/test_cache.py",
        pattern="**/tests/**",
        message="trial modified protected path",
    )


# The plan's example: baseline wall_time_s n=5, mean 1.80, stdev 0.04; minimize
# runtime with a 2 % minimum gain -> noise floor 0.08 s (4.4 %).
BASELINE_WALL = _measurement(W1, METRIC_WALL_TIME_S, 1.80, 0.04)
SPEED_BASELINE = _baseline(BASELINE_WALL, objectives=(_objective(),))
NOISE_FLOOR_REL = 0.08 / 1.80

PASSED = JudgeOutcome.passed
FAILED = JudgeOutcome.failed
INCONCLUSIVE = JudgeOutcome.inconclusive
NOT_APPLICABLE = JudgeOutcome.not_applicable


# ---------------------------------------------------------------------------
# Judge protocol and the default set
# ---------------------------------------------------------------------------


def test_default_judges_conform_to_the_protocol_in_order() -> None:
    """
    GIVEN the default judge set
    WHEN inspected
    THEN every judge satisfies the Judge protocol and they come in the fixed order
    """
    judges = default_judges()

    assert all(isinstance(judge, Judge) for judge in judges)
    assert [judge.name for judge in judges] == [
        "speed",
        "memory",
        "equivalence",
        "guardrail",
        "tests",
    ]
    assert isinstance(judges[0], SpeedJudge)
    assert isinstance(judges[1], MemoryJudge)
    assert isinstance(judges[2], EquivalenceJudge)
    assert isinstance(judges[3], GuardrailMetricJudge)
    assert isinstance(judges[4], SuiteJudge)


def test_default_judges_pass_the_noise_multiplier_to_the_gain_judges() -> None:
    """
    GIVEN a custom noise multiplier
    WHEN the default judges are built
    THEN both gain judges carry it and use the metric constants
    """
    speed, memory = default_judges(noise_multiplier=3.0)[:2]

    assert isinstance(speed, SpeedJudge)
    assert isinstance(memory, MemoryJudge)
    assert speed.noise_multiplier == 3.0
    assert memory.noise_multiplier == 3.0
    assert speed.metric == METRIC_WALL_TIME_S
    assert memory.metric == METRIC_PEAK_RSS_BYTES


def test_judges_are_frozen() -> None:
    """
    GIVEN a judge
    WHEN code tries to change its configuration
    THEN the frozen dataclass refuses (nothing a trial writes can alter a judge)
    """
    judge = SpeedJudge()
    field = "metric"

    with pytest.raises(FrozenInstanceError):
        setattr(judge, field, METRIC_PEAK_RSS_BYTES)


def test_something_without_evaluate_is_not_a_judge() -> None:
    """
    GIVEN an object that only has a name
    WHEN checked against the protocol
    THEN it is not a Judge
    """

    class Named:
        name = "impostor"

    assert not isinstance(Named(), Judge)


# ---------------------------------------------------------------------------
# MetricGainJudge, SpeedJudge, MemoryJudge
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("judge", "metric", "expected"),
    [
        (SpeedJudge(), METRIC_WALL_TIME_S, True),
        (SpeedJudge(), METRIC_PEAK_RSS_BYTES, False),
        (MemoryJudge(), METRIC_PEAK_RSS_BYTES, True),
        (MemoryJudge(), METRIC_WALL_TIME_S, False),
        (MetricGainJudge(METRIC_THROUGHPUT_PER_S), METRIC_THROUGHPUT_PER_S, True),
        (MetricGainJudge(METRIC_THROUGHPUT_PER_S), METRIC_WALL_TIME_S, False),
    ],
)
def test_gain_judges_apply_to_their_own_metric_only(
    judge: MetricGainJudge, metric: str, expected: bool
) -> None:
    """
    GIVEN a gain judge and an objective
    WHEN asked whether it applies
    THEN it does only when the objective targets the judge's metric
    """
    assert judge.applies_to(_objective(metric)) is expected


def test_gain_judge_names() -> None:
    """
    GIVEN the gain judges
    WHEN named
    THEN the thin subclasses have fixed names and the base names its metric
    """
    assert SpeedJudge().name == "speed"
    assert MemoryJudge().name == "memory"
    assert MetricGainJudge(METRIC_THROUGHPUT_PER_S).name == "gain:throughput_per_s"


def test_speed_judge_is_not_applicable_without_a_runtime_objective() -> None:
    """
    GIVEN a baseline whose only objective is peak memory
    WHEN the speed judge evaluates a trial
    THEN the outcome is not_applicable
    """
    baseline = _baseline(BASELINE_WALL, objectives=(_objective(METRIC_PEAK_RSS_BYTES),))

    result = SpeedJudge().evaluate(baseline, _trial())

    assert result.outcome is NOT_APPLICABLE
    assert result.judge == "speed"
    assert result.metric == METRIC_WALL_TIME_S
    assert "no objective" in result.reason


def test_speed_judge_passes_a_gain_beyond_the_noise_floor() -> None:
    """
    GIVEN baseline 1.80 +- 0.04 and trial 1.05 +- 0.03 (the plan's H1)
    WHEN the speed judge evaluates
    THEN it passes with a 41.7 % gain over a 4.4 % noise floor
    """
    trial = _trial(_measurement(W1, METRIC_WALL_TIME_S, 1.05))

    result = SpeedJudge().evaluate(SPEED_BASELINE, trial)

    assert result.outcome is PASSED
    assert result.metric == METRIC_WALL_TIME_S
    assert result.baseline == BASELINE_WALL.stats
    assert result.trial == trial.measurements[0].stats
    assert result.gain == pytest.approx(0.75 / 1.80)
    assert result.noise_floor == pytest.approx(NOISE_FLOOR_REL)
    assert result.details == {"workloads": 1}
    assert "41.7%" in result.reason


def test_speed_judge_is_inconclusive_inside_the_noise_floor() -> None:
    """
    GIVEN a trial of 1.76 (2.2 % gain, the plan's H3)
    WHEN the speed judge evaluates
    THEN it is inconclusive and reports the gain and the floor
    """
    trial = _trial(_measurement(W1, METRIC_WALL_TIME_S, 1.76))

    result = SpeedJudge().evaluate(SPEED_BASELINE, trial)

    assert result.outcome is INCONCLUSIVE
    assert result.gain == pytest.approx(0.04 / 1.80)
    assert result.noise_floor == pytest.approx(NOISE_FLOOR_REL)
    assert "inside the noise floor" in result.reason


def test_speed_judge_fails_a_regression_beyond_the_noise_floor() -> None:
    """
    GIVEN a trial of 2.10 (slower by more than the 0.08 s floor)
    WHEN the speed judge evaluates
    THEN it fails with a negative gain
    """
    trial = _trial(_measurement(W1, METRIC_WALL_TIME_S, 2.10))

    result = SpeedJudge().evaluate(SPEED_BASELINE, trial)

    assert result.outcome is FAILED
    assert result.gain == pytest.approx(-0.30 / 1.80)
    assert "regressed" in result.reason


def test_speed_judge_treats_a_regression_inside_the_floor_as_inconclusive() -> None:
    """
    GIVEN a trial of 1.84 (slower by 0.04 s, inside the 0.08 s floor)
    WHEN the speed judge evaluates
    THEN it is inconclusive, not failed: the slowdown is within noise
    """
    trial = _trial(_measurement(W1, METRIC_WALL_TIME_S, 1.84))

    result = SpeedJudge().evaluate(SPEED_BASELINE, trial)

    assert result.outcome is INCONCLUSIVE
    assert result.gain == pytest.approx(-0.04 / 1.80)


def test_speed_judge_is_inconclusive_without_a_trial_measurement() -> None:
    """
    GIVEN a trial that measured only memory
    WHEN the speed judge evaluates
    THEN it is inconclusive, names the missing metric and carries no gain
    """
    trial = _trial(_measurement(W1, METRIC_PEAK_RSS_BYTES, 1e9, unit="bytes"))

    result = SpeedJudge().evaluate(SPEED_BASELINE, trial)

    assert result.outcome is INCONCLUSIVE
    assert "no trial measurement for metric wall_time_s" in result.reason
    assert W1 in result.reason
    assert result.baseline == BASELINE_WALL.stats
    assert result.trial is None
    assert result.gain is None
    assert result.noise_floor is None
    assert result.details == {"workloads": 1}


def test_speed_judge_is_inconclusive_without_a_baseline_measurement() -> None:
    """
    GIVEN a baseline with a runtime objective but no wall-time measurement
    WHEN the speed judge evaluates
    THEN it is inconclusive (nothing to compare against)
    """
    baseline = _baseline(objectives=(_objective(),))
    trial = _trial(_measurement(W1, METRIC_WALL_TIME_S, 1.05))

    result = SpeedJudge().evaluate(baseline, trial)

    assert result.outcome is INCONCLUSIVE
    assert "no baseline measurement" in result.reason
    assert result.details == {"workloads": 0}


def test_speed_judge_reports_the_worst_workload_when_all_pass() -> None:
    """
    GIVEN two workloads, one 41.7 % faster and one 16.7 % faster
    WHEN the speed judge evaluates
    THEN it passes with the smaller gain and the stats of that workload
    """
    second_baseline = _measurement(W2, METRIC_WALL_TIME_S, 1.80, 0.04)
    baseline = _baseline(BASELINE_WALL, second_baseline, objectives=(_objective(),))
    slower = _measurement(W2, METRIC_WALL_TIME_S, 1.50)
    trial = _trial(_measurement(W1, METRIC_WALL_TIME_S, 1.05), slower)

    result = SpeedJudge().evaluate(baseline, trial)

    assert result.outcome is PASSED
    assert result.gain == pytest.approx(0.30 / 1.80)
    assert result.baseline == second_baseline.stats
    assert result.trial == slower.stats
    assert result.details == {"workloads": 2}


def test_speed_judge_is_inconclusive_when_one_workload_is_inside_noise() -> None:
    """
    GIVEN two workloads, one clearly faster and one inside the noise floor
    WHEN the speed judge evaluates
    THEN the whole result is inconclusive and names the weak workload
    """
    baseline = _baseline(
        BASELINE_WALL,
        _measurement(W2, METRIC_WALL_TIME_S, 1.80, 0.04),
        objectives=(_objective(),),
    )
    trial = _trial(
        _measurement(W1, METRIC_WALL_TIME_S, 1.05),
        _measurement(W2, METRIC_WALL_TIME_S, 1.76),
    )

    result = SpeedJudge().evaluate(baseline, trial)

    assert result.outcome is INCONCLUSIVE
    assert result.gain == pytest.approx(0.04 / 1.80)
    assert W2 in result.reason


def test_speed_judge_failure_beats_inconclusive_and_missing_workloads() -> None:
    """
    GIVEN three workloads: one passes, one regresses beyond noise, one unmeasured
    WHEN the speed judge evaluates
    THEN the regression makes the judge fail and the reason names that workload
    """
    baseline = _baseline(
        BASELINE_WALL,
        _measurement(W2, METRIC_WALL_TIME_S, 1.80, 0.04),
        _measurement(W3, METRIC_WALL_TIME_S, 1.80, 0.04),
        objectives=(_objective(),),
    )
    trial = _trial(
        _measurement(W1, METRIC_WALL_TIME_S, 1.05),
        _measurement(W2, METRIC_WALL_TIME_S, 2.10),
    )

    result = SpeedJudge().evaluate(baseline, trial)

    assert result.outcome is FAILED
    assert result.gain == pytest.approx(-0.30 / 1.80)
    assert W2 in result.reason
    assert result.details == {"workloads": 3}


def test_speed_judge_pairs_only_its_own_metric_and_first_measurement() -> None:
    """
    GIVEN trial measurements for several metrics and a duplicate wall-time row
    WHEN the speed judge evaluates
    THEN only the first wall-time measurement per workload is paired
    """
    trial = _trial(
        _measurement(W1, METRIC_PEAK_RSS_BYTES, 5e9, unit="bytes"),
        _measurement(W1, METRIC_WALL_TIME_S, 1.05),
        _measurement(W1, METRIC_WALL_TIME_S, 9.99),
    )

    result = SpeedJudge().evaluate(SPEED_BASELINE, trial)

    assert result.outcome is PASSED
    assert result.trial is not None
    assert result.trial.mean == 1.05


def test_noise_multiplier_raises_the_floor() -> None:
    """
    GIVEN a 5.6 % gain (1.80 -> 1.70) that clears a 2x floor but not a 3x floor
    WHEN judged with each multiplier
    THEN the 2x judge passes and the 3x judge is inconclusive
    """
    trial = _trial(_measurement(W1, METRIC_WALL_TIME_S, 1.70))

    relaxed = SpeedJudge().evaluate(SPEED_BASELINE, trial)
    strict = SpeedJudge(noise_multiplier=3.0).evaluate(SPEED_BASELINE, trial)

    assert relaxed.outcome is PASSED
    assert strict.outcome is INCONCLUSIVE
    assert strict.noise_floor == pytest.approx(0.12 / 1.80)


def test_memory_judge_uses_the_peak_rss_objective() -> None:
    """
    GIVEN a peak-memory objective and a trial using 40 % less memory
    WHEN the memory judge evaluates
    THEN it passes on the peak_rss_bytes metric
    """
    baseline = _baseline(
        _measurement(W1, METRIC_PEAK_RSS_BYTES, 1e9, 1e7, unit="bytes"),
        objectives=(_objective(METRIC_PEAK_RSS_BYTES, kind=ObjectiveKind.peak_memory),),
    )
    trial = _trial(_measurement(W1, METRIC_PEAK_RSS_BYTES, 6e8, 1e7, unit="bytes"))

    result = MemoryJudge().evaluate(baseline, trial)

    assert result.outcome is PASSED
    assert result.judge == "memory"
    assert result.metric == METRIC_PEAK_RSS_BYTES
    assert result.gain == pytest.approx(0.4)


def test_gain_judge_honours_a_maximize_objective() -> None:
    """
    GIVEN a throughput objective (maximize) and a trial with 50 % more throughput
    WHEN a generic gain judge evaluates
    THEN it passes with a positive gain, and a drop fails
    """
    judge = MetricGainJudge(METRIC_THROUGHPUT_PER_S)
    baseline = _baseline(
        _measurement(W1, METRIC_THROUGHPUT_PER_S, 100.0, 1.0, unit="1/s"),
        objectives=(
            _objective(
                METRIC_THROUGHPUT_PER_S,
                Direction.maximize,
                kind=ObjectiveKind.throughput,
            ),
        ),
    )
    faster = _trial(_measurement(W1, METRIC_THROUGHPUT_PER_S, 150.0, 1.0, unit="1/s"))
    slower = _trial(_measurement(W1, METRIC_THROUGHPUT_PER_S, 50.0, 1.0, unit="1/s"))

    assert judge.evaluate(baseline, faster).outcome is PASSED
    assert judge.evaluate(baseline, faster).gain == pytest.approx(0.5)
    assert judge.evaluate(baseline, slower).outcome is FAILED


# ---------------------------------------------------------------------------
# EquivalenceJudge
# ---------------------------------------------------------------------------


def test_equivalence_judge_applies_to_every_objective() -> None:
    """
    GIVEN any objective
    WHEN the equivalence judge is asked whether it applies
    THEN it always does (outputs must not change regardless of the metric)
    """
    judge = EquivalenceJudge()

    assert judge.name == "equivalence"
    assert judge.applies_to(_objective()) is True
    assert judge.applies_to(_objective(METRIC_PEAK_RSS_BYTES)) is True


def test_equivalence_judge_is_not_applicable_without_the_guardrail() -> None:
    """
    GIVEN a baseline without an output_equivalence guardrail
    WHEN the equivalence judge evaluates
    THEN the outcome is not_applicable even if fingerprints differ
    """
    baseline = _baseline(
        _measurement(W1, METRIC_WALL_TIME_S, 1.80, digest=fingerprint("a"))
    )
    trial = _trial(_measurement(W1, METRIC_WALL_TIME_S, 1.05, digest=fingerprint("b")))

    result = EquivalenceJudge().evaluate(baseline, trial)

    assert result.outcome is NOT_APPLICABLE
    assert result.metric is None


def test_equivalence_judge_passes_identical_outputs() -> None:
    """
    GIVEN an output_equivalence guardrail and equal fingerprints per workload
    WHEN the equivalence judge evaluates
    THEN it passes and counts the workloads compared
    """
    guardrails = (_guardrail(GuardrailKind.output_equivalence),)
    baseline = _baseline(
        _measurement(W1, METRIC_WALL_TIME_S, 1.80, digest=fingerprint("a")),
        _measurement(W2, METRIC_WALL_TIME_S, 1.80, digest=fingerprint("b")),
        guardrails=guardrails,
    )
    trial = _trial(
        _measurement(W1, METRIC_WALL_TIME_S, 1.05, digest=fingerprint("a")),
        _measurement(W2, METRIC_WALL_TIME_S, 1.05, digest=fingerprint("b")),
    )

    result = EquivalenceJudge().evaluate(baseline, trial)

    assert result.outcome is PASSED
    assert result.details == {"workloads": 2}


def test_equivalence_judge_fails_on_changed_or_missing_output() -> None:
    """
    GIVEN one workload whose output changed and one the trial has no digest for
    WHEN the equivalence judge evaluates
    THEN it fails and the reason lists both violations
    """
    guardrails = (_guardrail(GuardrailKind.output_equivalence),)
    baseline = _baseline(
        _measurement(W1, METRIC_WALL_TIME_S, 1.80, digest=fingerprint("a")),
        _measurement(W2, METRIC_WALL_TIME_S, 1.80, digest=fingerprint("b")),
        guardrails=guardrails,
    )
    trial = _trial(
        _measurement(W1, METRIC_WALL_TIME_S, 1.05, digest=fingerprint("changed")),
        _measurement(W2, METRIC_WALL_TIME_S, 1.05),
    )

    result = EquivalenceJudge().evaluate(baseline, trial)

    assert result.outcome is FAILED
    assert f"workload {W1}: output changed" in result.reason
    assert f"workload {W2}: no output fingerprint on trial" in result.reason


def test_equivalence_judge_is_inconclusive_with_nothing_to_compare() -> None:
    """
    GIVEN an output_equivalence guardrail but no baseline measurements
    WHEN the equivalence judge evaluates
    THEN it is inconclusive rather than vacuously passing
    """
    baseline = _baseline(guardrails=(_guardrail(GuardrailKind.output_equivalence),))

    result = EquivalenceJudge().evaluate(baseline, _trial())

    assert result.outcome is INCONCLUSIVE
    assert result.details == {"workloads": 0}


# ---------------------------------------------------------------------------
# GuardrailMetricJudge
# ---------------------------------------------------------------------------


def _loss_baseline(*guardrails: Guardrail, mean: float = 0.500) -> Baseline:
    return _baseline(
        _measurement(W1, VAL_LOSS, mean, 0.001, unit="nats"), guardrails=guardrails
    )


def _loss_trial(mean: float) -> Trial:
    return _trial(_measurement(W1, VAL_LOSS, mean, 0.001, unit="nats"))


def test_guardrail_judge_applies_to_every_objective() -> None:
    """
    GIVEN any objective
    WHEN the guardrail judge is asked whether it applies
    THEN it always does
    """
    judge = GuardrailMetricJudge()

    assert judge.name == "guardrail"
    assert judge.applies_to(_objective()) is True


def test_guardrail_judge_is_not_applicable_without_metric_bounds() -> None:
    """
    GIVEN only tests_pass and output_equivalence guardrails
    WHEN the guardrail judge evaluates
    THEN the outcome is not_applicable
    """
    baseline = _baseline(
        guardrails=(
            _guardrail(GuardrailKind.tests_pass),
            _guardrail(GuardrailKind.output_equivalence),
        )
    )

    result = GuardrailMetricJudge().evaluate(baseline, _trial())

    assert result.outcome is NOT_APPLICABLE
    assert result.details == {"guardrails": 0}


def test_guardrail_judge_passes_a_drop_within_the_bound() -> None:
    """
    GIVEN val_loss may drop at most 1 % and the trial's loss rose 0.6 % (H4)
    WHEN the guardrail judge evaluates
    THEN it passes, gain is minus the drop and metric stays None (not an objective)
    """
    baseline = _loss_baseline(_bound(VAL_LOSS, 0.01))

    result = GuardrailMetricJudge().evaluate(baseline, _loss_trial(0.503))

    assert result.outcome is PASSED
    assert result.metric is None
    assert result.gain == pytest.approx(-0.006)
    assert result.baseline == baseline.measurements[0].stats
    assert result.trial is not None
    assert result.trial.mean == 0.503
    assert result.details == {"guardrails": 1, "metric": VAL_LOSS, "max_drop": 0.01}


def test_guardrail_judge_passes_exactly_on_the_bound() -> None:
    """
    GIVEN a drop of exactly max_drop (1 % of 0.500 = 0.505)
    WHEN the guardrail judge evaluates
    THEN it passes: only a drop strictly beyond the bound fails
    """
    baseline = _loss_baseline(_bound(VAL_LOSS, 0.01))

    result = GuardrailMetricJudge().evaluate(baseline, _loss_trial(0.505))

    assert result.outcome is PASSED
    assert result.gain == pytest.approx(-0.01)


def test_guardrail_judge_fails_a_drop_beyond_the_bound() -> None:
    """
    GIVEN a 2 % rise in val_loss against a 1 % bound
    WHEN the guardrail judge evaluates
    THEN it fails and the reason names metric, drop and bound
    """
    baseline = _loss_baseline(_bound(VAL_LOSS, 0.01))

    result = GuardrailMetricJudge().evaluate(baseline, _loss_trial(0.510))

    assert result.outcome is FAILED
    assert result.gain == pytest.approx(-0.02)
    assert VAL_LOSS in result.reason
    assert "2.0%" in result.reason
    assert "1.0%" in result.reason


def test_guardrail_judge_treats_an_improvement_as_a_negative_drop() -> None:
    """
    GIVEN val_loss fell from 0.500 to 0.450
    WHEN the guardrail judge evaluates
    THEN it passes with a positive gain of 10 %
    """
    baseline = _loss_baseline(_bound(VAL_LOSS, 0.01))

    result = GuardrailMetricJudge().evaluate(baseline, _loss_trial(0.450))

    assert result.outcome is PASSED
    assert result.gain == pytest.approx(0.10)


def test_guardrail_judge_honours_a_maximize_metric() -> None:
    """
    GIVEN accuracy (maximize) may drop at most 1 %
    WHEN accuracy falls 2.2 % and, separately, 0.6 %
    THEN the first fails and the second passes
    """
    baseline = _baseline(
        _measurement(W1, ACCURACY, 0.900, 0.001, unit="ratio"),
        guardrails=(_bound(ACCURACY, 0.01, Direction.maximize),),
    )
    judge = GuardrailMetricJudge()

    worse = judge.evaluate(
        baseline, _trial(_measurement(W1, ACCURACY, 0.880, 0.001, unit="ratio"))
    )
    fine = judge.evaluate(
        baseline, _trial(_measurement(W1, ACCURACY, 0.895, 0.001, unit="ratio"))
    )

    assert worse.outcome is FAILED
    assert worse.gain == pytest.approx(-0.02 / 0.9)
    assert fine.outcome is PASSED


def test_guardrail_judge_is_inconclusive_when_a_measurement_is_missing() -> None:
    """
    GIVEN a guardrail whose metric the trial (or the baseline) did not measure
    WHEN the guardrail judge evaluates
    THEN it is inconclusive and names what is missing
    """
    judge = GuardrailMetricJudge()
    baseline = _loss_baseline(_bound(VAL_LOSS, 0.01))

    no_trial = judge.evaluate(baseline, _trial())
    no_baseline = judge.evaluate(
        _baseline(guardrails=(_bound(VAL_LOSS, 0.01),)), _loss_trial(0.5)
    )

    assert no_trial.outcome is INCONCLUSIVE
    assert f"no trial measurement for {VAL_LOSS}" in no_trial.reason
    assert no_trial.gain is None
    assert no_baseline.outcome is INCONCLUSIVE
    assert f"no baseline measurement for {VAL_LOSS}" in no_baseline.reason


def test_guardrail_judge_is_inconclusive_when_the_baseline_mean_is_zero() -> None:
    """
    GIVEN a baseline metric of exactly zero
    WHEN the guardrail judge evaluates
    THEN it is inconclusive (a relative drop is undefined)
    """
    baseline = _loss_baseline(_bound(VAL_LOSS, 0.01), mean=0.0)

    result = GuardrailMetricJudge().evaluate(baseline, _loss_trial(0.1))

    assert result.outcome is INCONCLUSIVE
    assert "zero" in result.reason


def test_guardrail_judge_reports_the_worst_drop_across_guardrails_and_workloads() -> (
    None
):
    """
    GIVEN two bounded metrics over two workloads, all within their bounds
    WHEN the guardrail judge evaluates
    THEN it passes and reports the largest drop (accuracy on w2)
    """
    baseline = _baseline(
        _measurement(W1, VAL_LOSS, 0.500, 0.001, unit="nats"),
        _measurement(W2, VAL_LOSS, 0.500, 0.001, unit="nats"),
        _measurement(W1, ACCURACY, 0.900, 0.001, unit="ratio"),
        _measurement(W2, ACCURACY, 0.900, 0.001, unit="ratio"),
        guardrails=(
            _bound(VAL_LOSS, 0.01),
            _bound(ACCURACY, 0.02, Direction.maximize),
        ),
    )
    trial = _trial(
        _measurement(W1, VAL_LOSS, 0.501, 0.001, unit="nats"),
        _measurement(W2, VAL_LOSS, 0.502, 0.001, unit="nats"),
        _measurement(W1, ACCURACY, 0.899, 0.001, unit="ratio"),
        _measurement(W2, ACCURACY, 0.891, 0.001, unit="ratio"),
    )

    result = GuardrailMetricJudge().evaluate(baseline, trial)

    assert result.outcome is PASSED
    assert result.gain == pytest.approx(-0.009 / 0.9)
    assert result.details == {"guardrails": 2, "metric": ACCURACY, "max_drop": 0.02}
    assert W2 in result.reason


def test_guardrail_judge_failure_beats_a_missing_measurement() -> None:
    """
    GIVEN one guardrail breached and another unmeasured
    WHEN the guardrail judge evaluates
    THEN the breach makes it fail (a proven breach outranks missing data)
    """
    baseline = _baseline(
        _measurement(W1, VAL_LOSS, 0.500, 0.001, unit="nats"),
        guardrails=(_bound(VAL_LOSS, 0.01), _bound(ACCURACY, 0.01, Direction.maximize)),
    )

    result = GuardrailMetricJudge().evaluate(baseline, _loss_trial(0.520))

    assert result.outcome is FAILED
    assert result.details == {"guardrails": 2, "metric": VAL_LOSS, "max_drop": 0.01}


def test_guardrail_judge_rejects_an_incomplete_metric_bound() -> None:
    """
    GIVEN a metric_bound guardrail built without validation (no max_drop)
    WHEN the guardrail judge evaluates
    THEN it raises instead of guessing a bound
    """
    broken = Guardrail.model_construct(
        id="g",
        project_id=PROJECT,
        kind=GuardrailKind.metric_bound,
        metric=VAL_LOSS,
        max_drop=None,
        direction=Direction.minimize,
        description="broken",
    )
    baseline = Baseline.model_construct(guardrails=(broken,))

    with pytest.raises(ValueError, match="incomplete"):
        GuardrailMetricJudge().evaluate(baseline, _trial())


# ---------------------------------------------------------------------------
# TestSuiteJudge
# ---------------------------------------------------------------------------


def _tests(workload_id: str, pass_rate: float) -> Measurement:
    return _measurement(workload_id, METRIC_TESTS_PASSED, pass_rate, 0.0, unit="ratio")


def test_test_suite_judge_applies_to_every_objective() -> None:
    """
    GIVEN any objective
    WHEN the test-suite judge is asked whether it applies
    THEN it always does
    """
    judge = SuiteJudge()

    assert judge.name == "tests"
    assert judge.applies_to(_objective(METRIC_PEAK_RSS_BYTES)) is True


def test_test_suite_judge_is_not_applicable_without_the_guardrail() -> None:
    """
    GIVEN no tests_pass guardrail
    WHEN the test-suite judge evaluates a failing test run
    THEN the outcome is not_applicable
    """
    result = SuiteJudge().evaluate(_baseline(), _trial(_tests(W1, 0.0)))

    assert result.outcome is NOT_APPLICABLE


def test_test_suite_judge_is_inconclusive_without_a_measurement() -> None:
    """
    GIVEN a tests_pass guardrail but no tests_passed measurement on the trial
    WHEN the test-suite judge evaluates
    THEN it is inconclusive
    """
    baseline = _baseline(guardrails=(_guardrail(GuardrailKind.tests_pass),))

    result = SuiteJudge().evaluate(baseline, _trial())

    assert result.outcome is INCONCLUSIVE
    assert METRIC_TESTS_PASSED in result.reason


def test_test_suite_judge_passes_when_every_run_passed() -> None:
    """
    GIVEN a tests_passed mean of exactly 1.0 on every workload
    WHEN the test-suite judge evaluates
    THEN it passes and carries the trial stats
    """
    baseline = _baseline(guardrails=(_guardrail(GuardrailKind.tests_pass),))
    trial = _trial(_tests(W1, 1.0), _tests(W2, 1.0))

    result = SuiteJudge().evaluate(baseline, trial)

    assert result.outcome is PASSED
    assert result.metric is None
    assert result.trial == trial.measurements[0].stats
    assert result.details == {"workloads": 2}


def test_test_suite_judge_fails_when_any_run_failed() -> None:
    """
    GIVEN tests passed on w1 but only 80 % of runs on w2
    WHEN the test-suite judge evaluates
    THEN it fails and names the failing workload
    """
    baseline = _baseline(guardrails=(_guardrail(GuardrailKind.tests_pass),))
    trial = _trial(_tests(W1, 1.0), _tests(W2, 0.8))

    result = SuiteJudge().evaluate(baseline, trial)

    assert result.outcome is FAILED
    assert W2 in result.reason
    assert result.trial == trial.measurements[1].stats


# ---------------------------------------------------------------------------
# derive_verdict: the six ordered rules
# ---------------------------------------------------------------------------

SPEED_OK = _result("speed", PASSED, metric=METRIC_WALL_TIME_S, gain=0.4)
MEMORY_NA = _result("memory", NOT_APPLICABLE, metric=METRIC_PEAK_RSS_BYTES)
TESTS_OK = _result("tests", PASSED)


def _verdict(
    results: Sequence[JudgeResult],
    violations: Sequence[Violation] = (),
    *,
    change_class: ChangeClass = ChangeClass.efficiency,
    status: TrialStatus = TrialStatus.measured,
    primary: str | None = None,
) -> Verdict:
    return derive_verdict(
        _trial(status=status),
        _hypothesis(change_class),
        results,
        violations,
        primary_metric=primary,
    )


def test_rule_1_a_violation_beats_passing_judges() -> None:
    """
    GIVEN every judge passed but the diff touched a protected path (the plan's H2)
    WHEN the verdict is derived
    THEN it is reject, the violation is carried and the summary names the rule
    """
    verdict = _verdict((SPEED_OK, TESTS_OK), (_violation(),))

    assert verdict.outcome is VerdictOutcome.reject
    assert verdict.violations == (_violation(),)
    assert verdict.judge_results == (SPEED_OK, TESTS_OK)
    assert verdict.summary.startswith("reject:")
    assert "protected_path" in verdict.summary
    assert verdict.gain == 0.4


def test_rule_2_a_failed_or_rejected_trial_is_rejected() -> None:
    """
    GIVEN a trial whose status is failed (or rejected) with passing judge results
    WHEN the verdict is derived
    THEN it is reject and the summary names the trial status
    """
    failed = _verdict((SPEED_OK,), status=TrialStatus.failed)
    rejected = _verdict((SPEED_OK,), status=TrialStatus.rejected)

    assert failed.outcome is VerdictOutcome.reject
    assert "trial failed" in failed.summary
    assert rejected.outcome is VerdictOutcome.reject
    assert "trial rejected" in rejected.summary


def test_rule_2_carries_the_trial_error_in_the_summary() -> None:
    """
    GIVEN a failed trial with an error message
    WHEN the verdict is derived
    THEN the summary includes the error
    """
    verdict = derive_verdict(
        _trial(status=TrialStatus.failed, error="worktree build failed"),
        _hypothesis(),
        (),
        (),
    )

    assert verdict.outcome is VerdictOutcome.reject
    assert "worktree build failed" in verdict.summary


def test_rule_3_a_failed_judge_rejects_even_with_inconclusive_judges() -> None:
    """
    GIVEN one judge failed and another inconclusive
    WHEN the verdict is derived
    THEN it is reject naming the failed judge (rule 3 precedes rule 4)
    """
    results = (
        _result("speed", INCONCLUSIVE, metric=METRIC_WALL_TIME_S, gain=0.01),
        _result("tests", FAILED),
    )

    verdict = _verdict(results)

    assert verdict.outcome is VerdictOutcome.reject
    assert "judge tests failed" in verdict.summary


def test_rule_4_an_inconclusive_judge_makes_the_verdict_inconclusive() -> None:
    """
    GIVEN a speed gain inside the noise floor (the plan's H3)
    WHEN the verdict is derived
    THEN it is inconclusive naming that judge
    """
    results = (
        _result("speed", INCONCLUSIVE, metric=METRIC_WALL_TIME_S, gain=0.022),
        TESTS_OK,
    )

    verdict = _verdict(results)

    assert verdict.outcome is VerdictOutcome.inconclusive
    assert "judge speed inconclusive" in verdict.summary
    assert verdict.gain == 0.022


@pytest.mark.parametrize(
    "results",
    [
        (),
        (MEMORY_NA, TESTS_OK),
        (_result("equivalence", PASSED), _result("guardrail", PASSED)),
    ],
    ids=["no judges", "objective judge not applicable", "only guardrail judges"],
)
def test_rule_5_without_a_passed_objective_judge_nothing_is_proved(
    results: Sequence[JudgeResult],
) -> None:
    """
    GIVEN no passed judge that carries a metric
    WHEN the verdict is derived
    THEN it is inconclusive: nothing proved better
    """
    verdict = _verdict(results)

    assert verdict.outcome is VerdictOutcome.inconclusive
    assert "nothing proved better" in verdict.summary
    assert verdict.gain is None


def test_rule_6_efficiency_change_with_all_judges_passed_is_kept() -> None:
    """
    GIVEN an efficiency hypothesis whose judges all passed (the plan's H1)
    WHEN the verdict is derived
    THEN it is keep, with the gain and the hypothesis' change class
    """
    verdict = _verdict((SPEED_OK, MEMORY_NA, TESTS_OK))

    assert verdict.outcome is VerdictOutcome.keep
    assert verdict.change_class is ChangeClass.efficiency
    assert verdict.gain == 0.4
    assert verdict.summary.startswith("keep:")
    assert verdict.approved_by is None


@pytest.mark.parametrize("change_class", [ChangeClass.behaviour, ChangeClass.novel])
def test_rule_6_behaviour_and_novel_changes_need_approval(
    change_class: ChangeClass,
) -> None:
    """
    GIVEN a behaviour-changing (or novel) hypothesis whose judges all passed (H4)
    WHEN the verdict is derived
    THEN it is needs_approval and names the change class
    """
    verdict = _verdict((SPEED_OK, TESTS_OK), change_class=change_class)

    assert verdict.outcome is VerdictOutcome.needs_approval
    assert verdict.change_class is change_class
    assert str(change_class) in verdict.summary


def test_verdict_copies_ids_and_is_pure() -> None:
    """
    GIVEN a trial and a hypothesis
    WHEN the verdict is derived twice
    THEN ids come from the inputs and the inputs are untouched
    """
    trial = _trial()
    hypothesis = _hypothesis()

    first = derive_verdict(trial, hypothesis, (SPEED_OK,), ())
    second = derive_verdict(trial, hypothesis, (SPEED_OK,), ())

    assert first.trial_id == trial.id
    assert first.hypothesis_id == hypothesis.id
    assert first.outcome is second.outcome
    assert first.summary == second.summary
    assert trial.judge_results == ()


def test_gain_prefers_the_passed_primary_metric_judge() -> None:
    """
    GIVEN speed and memory both passed with different gains
    WHEN the verdict is derived with peak memory as the primary metric
    THEN the verdict gain is the memory gain; without a primary it is the first
    """
    memory_ok = _result("memory", PASSED, metric=METRIC_PEAK_RSS_BYTES, gain=0.1)

    by_primary = _verdict((SPEED_OK, memory_ok), primary=METRIC_PEAK_RSS_BYTES)
    by_order = _verdict((SPEED_OK, memory_ok))

    assert by_primary.gain == 0.1
    assert by_order.gain == 0.4


def test_gain_falls_back_to_the_first_objective_judge_with_a_gain() -> None:
    """
    GIVEN the primary metric's judge did not pass and the memory judge has no gain
    WHEN the verdict is derived
    THEN the gain comes from the first objective judge that measured one
    """
    results = (
        MEMORY_NA,
        _result("speed", INCONCLUSIVE, metric=METRIC_WALL_TIME_S, gain=0.02),
        _result("tests", PASSED, gain=0.99),
    )

    verdict = _verdict(results, primary=METRIC_WALL_TIME_S)

    assert verdict.gain == 0.02


# ---------------------------------------------------------------------------
# primary_metric
# ---------------------------------------------------------------------------


def test_primary_metric_is_the_highest_weight_first_on_ties() -> None:
    """
    GIVEN objectives with weights 1, 3, 3
    WHEN the primary metric is chosen
    THEN it is the first objective with the highest weight
    """
    objectives = (
        _objective(METRIC_WALL_TIME_S, weight=1.0),
        _objective(METRIC_PEAK_RSS_BYTES, weight=3.0),
        _objective(METRIC_THROUGHPUT_PER_S, Direction.maximize, weight=3.0),
    )

    assert primary_metric(objectives) == METRIC_PEAK_RSS_BYTES
    assert primary_metric(objectives[:1]) == METRIC_WALL_TIME_S
    assert primary_metric(()) is None


# ---------------------------------------------------------------------------
# The plan's example, end to end through the default judges
# ---------------------------------------------------------------------------

EXAMPLE_BASELINE = _baseline(
    BASELINE_WALL,
    _measurement(W1, VAL_LOSS, 0.500, 0.001, unit="nats"),
    objectives=(_objective(),),
    guardrails=(_guardrail(GuardrailKind.tests_pass), _bound(VAL_LOSS, 0.01)),
)


def _judge_all(trial: Trial) -> tuple[JudgeResult, ...]:
    return tuple(judge.evaluate(EXAMPLE_BASELINE, trial) for judge in default_judges())


def _example_trial(
    wall_time: float, val_loss: float = 0.500, *, touched: str = "src/bridge/encoder.py"
) -> Trial:
    return _trial(
        _measurement(W1, METRIC_WALL_TIME_S, wall_time),
        _measurement(W1, VAL_LOSS, val_loss, 0.001, unit="nats"),
        _tests(W1, 1.0),
        touched_paths=(touched,),
    )


def test_example_h1_cache_embeddings_is_kept() -> None:
    """
    GIVEN H1: 1.05 s, tests pass, val_loss unchanged, efficiency class
    WHEN judged and the verdict derived
    THEN speed, guardrail and tests pass, memory and equivalence do not apply -> keep
    """
    trial = _example_trial(1.05)
    results = _judge_all(trial)

    verdict = derive_verdict(trial, _hypothesis(), results, ())

    assert [r.outcome for r in results] == [
        PASSED,
        NOT_APPLICABLE,
        NOT_APPLICABLE,
        PASSED,
        PASSED,
    ]
    assert verdict.outcome is VerdictOutcome.keep
    assert verdict.gain == pytest.approx(0.75 / 1.80)


def test_example_h2_touching_tests_is_rejected_despite_a_speedup() -> None:
    """
    GIVEN H2: 1.20 s but the diff edits tests/test_cache.py
    WHEN judged with the anti-cheating violations
    THEN the verdict is reject although the speed judge passed
    """
    trial = _example_trial(1.20, touched="tests/test_cache.py")
    results = _judge_all(trial)
    violations = check_diff_all(trial.touched_paths)

    verdict = derive_verdict(trial, _hypothesis(), results, violations)

    assert results[0].outcome is PASSED
    assert verdict.outcome is VerdictOutcome.reject
    assert verdict.violations[0].rule is ViolationRule.protected_path


def test_example_h3_micro_tweak_is_inconclusive() -> None:
    """
    GIVEN H3: 1.76 s (2.2 % gain inside the 4.4 % noise floor)
    WHEN judged
    THEN the verdict is inconclusive
    """
    trial = _example_trial(1.76)

    verdict = derive_verdict(trial, _hypothesis(), _judge_all(trial), ())

    assert verdict.outcome is VerdictOutcome.inconclusive


def test_example_h4_bf16_autocast_needs_approval() -> None:
    """
    GIVEN H4: 1.50 s, val_loss up 0.6 % (within 1 %), behaviour class
    WHEN judged
    THEN speed and guardrail pass and the verdict is needs_approval
    """
    trial = _example_trial(1.50, val_loss=0.503)
    results = _judge_all(trial)

    verdict = derive_verdict(trial, _hypothesis(ChangeClass.behaviour), results, ())

    assert results[3].outcome is PASSED
    assert verdict.outcome is VerdictOutcome.needs_approval
    assert verdict.gain == pytest.approx(0.30 / 1.80)


# ---------------------------------------------------------------------------
# Review fixes: per-workload floors, secondary objectives are neutral
# ---------------------------------------------------------------------------


def test_metric_gain_judge_requires_every_workload_to_clear_its_own_floor() -> None:
    """
    GIVEN a noisy workload whose 10% gain sits inside its own floor and a quiet
          workload whose 5% gain clears its floor
    WHEN the speed judge evaluates the trial
    THEN the result is inconclusive and names the noisy workload
    """
    from autonomous_ai_agents.common.models import (
        METRIC_WALL_TIME_S,
        Baseline,
        Direction,
        Hypothesis,
        HypothesisSource,
        Measurement,
        Objective,
        ObjectiveKind,
        RunStats,
        Trial,
        TrialStatus,
    )
    from autonomous_ai_agents.optimization.judges import SpeedJudge

    def measurement(
        workload: str, samples: tuple[float, ...], trial_id: str | None
    ) -> Measurement:
        return Measurement(
            workload_id=workload,
            trial_id=trial_id,
            metric=METRIC_WALL_TIME_S,
            stats=RunStats.from_samples(samples, unit="s"),
            samples=samples,
        )

    objective = Objective(
        project_id="p",
        kind=ObjectiveKind.runtime,
        metric=METRIC_WALL_TIME_S,
        direction=Direction.minimize,
        min_relative_gain=0.02,
        description="runtime",
    )
    baseline = Baseline(
        measurements=(
            measurement("noisy", (1.6, 1.8, 2.0, 1.8, 1.8), None),
            measurement("quiet", (1.0, 1.0, 1.0, 1.0, 1.0), None),
        ),
        objectives=(objective,),
    )
    hypothesis = Hypothesis(
        project_id="p",
        source=HypothesisSource.playbook,
        title="t",
        rationale="r",
        change_class=ChangeClass.efficiency,
        expected_gain=0.1,
        provability=0.9,
        risk=0.1,
    )
    trial = Trial(
        hypothesis_id=hypothesis.id,
        round=1,
        status=TrialStatus.measured,
        measurements=(
            measurement("noisy", (1.62,) * 5, "t1"),
            measurement("quiet", (0.95,) * 5, "t1"),
        ),
    )

    result = SpeedJudge().evaluate(baseline, trial)

    assert result.outcome is JudgeOutcome.inconclusive
    assert "noisy" in result.reason


def test_secondary_objective_inside_noise_is_neutral_but_primary_is_not() -> None:
    """
    GIVEN a passed primary-metric judge and an inconclusive secondary one
    WHEN the verdict is derived with each metric as primary in turn
    THEN the secondary inside its noise is neutral (keep), the primary is not,
         and an inconclusive guardrail judge always blocks
    """
    from autonomous_ai_agents.common.models import (
        METRIC_PEAK_RSS_BYTES,
        METRIC_WALL_TIME_S,
        Hypothesis,
        HypothesisSource,
        JudgeResult,
        Trial,
        TrialStatus,
    )
    from autonomous_ai_agents.optimization.judges import derive_verdict

    hypothesis = Hypothesis(
        project_id="p",
        source=HypothesisSource.playbook,
        title="t",
        rationale="r",
        change_class=ChangeClass.efficiency,
        expected_gain=0.1,
        provability=0.9,
        risk=0.1,
    )
    trial = Trial(hypothesis_id=hypothesis.id, round=1, status=TrialStatus.measured)
    speed = JudgeResult(
        judge="speed",
        outcome=JudgeOutcome.passed,
        metric=METRIC_WALL_TIME_S,
        gain=0.4,
        reason="x",
    )
    memory = JudgeResult(
        judge="memory",
        outcome=JudgeOutcome.inconclusive,
        metric=METRIC_PEAK_RSS_BYTES,
        reason="inside noise",
    )
    guard = JudgeResult(
        judge="guardrail", outcome=JudgeOutcome.inconclusive, reason="missing"
    )

    keep = derive_verdict(
        trial, hypothesis, (speed, memory), (), primary_metric=METRIC_WALL_TIME_S
    )
    blocked = derive_verdict(
        trial, hypothesis, (speed, memory), (), primary_metric=METRIC_PEAK_RSS_BYTES
    )
    guarded = derive_verdict(
        trial, hypothesis, (speed, guard), (), primary_metric=METRIC_WALL_TIME_S
    )

    assert keep.outcome is VerdictOutcome.keep
    assert blocked.outcome is VerdictOutcome.inconclusive
    assert guarded.outcome is VerdictOutcome.inconclusive
