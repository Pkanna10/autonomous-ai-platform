"""The scaling judge (G6b, spec section 2): shadow mode, records only.

``ScalingJudge`` fits, per workload and side, how run time grows with input
size: the least-squares slope of log(median time) against log(size) over the
sizes both sides ran (the growth rate: 1 linear, 2 quadratic). It records
both rates and their difference in a ``JudgeResult`` whose outcome is always
``not_applicable``. It never decides: ``derive_verdict`` gives exactly the
same verdict with or without it, whatever its result says. Hand-built
models, no I/O.
"""

from __future__ import annotations

import itertools
import math

import pytest

from autonomous_ai_agents.common.models import (
    METRIC_TESTS_PASSED,
    METRIC_WALL_TIME_S,
    Baseline,
    ChangeClass,
    Direction,
    Guardrail,
    GuardrailKind,
    Hypothesis,
    HypothesisSource,
    JsonScalar,
    JudgeOutcome,
    JudgeResult,
    Measurement,
    Objective,
    ObjectiveKind,
    RunStats,
    Trial,
    TrialStatus,
    Verdict,
    Violation,
    ViolationRule,
)
from autonomous_ai_agents.execution.measure import METRIC_SCALE_WALL_S, SCALE_SIZE_KEY
from autonomous_ai_agents.optimization.anticheat import fingerprint
from autonomous_ai_agents.optimization.judges import (
    GROWTH_TOLERANCE,
    OP_COUNT_JUDGE,
    SCALING_JUDGE,
    SHADOW_JUDGES,
    Judge,
    OpCountJudge,
    ScalingJudge,
    default_judges,
    derive_verdict,
    growth_rate,
)

P, W1, W2 = "project-1", "w1", "w2"
DIGEST = fingerprint("out")
SIZES = (1000, 2000, 4000)


def at(workload: str, size: JsonScalar, *seconds: float, trial_id: str | None = None) -> Measurement:  # fmt: skip
    return Measurement(
        workload_id=workload, trial_id=trial_id, metric=METRIC_SCALE_WALL_S,
        stats=RunStats.from_samples(seconds, unit="s"), samples=seconds,
        hardware={SCALE_SIZE_KEY: size},
    )  # fmt: skip


def grows(workload: str, power: float, factor: float = 1e-8, sizes: tuple[int, ...] = SIZES, trial_id: str | None = None) -> tuple[Measurement, ...]:  # fmt: skip
    """Rows for ``factor * size**power`` seconds, three runs a size."""
    return tuple(at(workload, s, *(factor * s**power,) * 3, trial_id=trial_id) for s in sizes)  # fmt: skip


def wall(workload: str, mean: float) -> Measurement:
    return Measurement(
        workload_id=workload, metric=METRIC_WALL_TIME_S,
        stats=RunStats(n=5, mean=mean, stdev=0.01, min=mean - 0.01, max=mean + 0.01, unit="s"),
        samples=(mean,) * 5, output_fingerprint=DIGEST,
    )  # fmt: skip


def tests_row(workload: str, passed: float = 1.0) -> Measurement:
    return Measurement(
        workload_id=workload, metric=METRIC_TESTS_PASSED,
        stats=RunStats.from_samples((passed,), unit="bool"), samples=(passed,),
    )  # fmt: skip


OBJECTIVE = Objective(
    project_id=P, kind=ObjectiveKind.runtime, metric=METRIC_WALL_TIME_S,
    direction=Direction.minimize, description="minimize wall time",
)  # fmt: skip
GUARDRAILS = (
    Guardrail(project_id=P, kind=GuardrailKind.output_equivalence, description="eq"),
    Guardrail(project_id=P, kind=GuardrailKind.tests_pass, description="tests"),
)


def baseline(*rows: Measurement) -> Baseline:
    return Baseline(measurements=rows, objectives=(OBJECTIVE,), guardrails=GUARDRAILS)


def trial(*rows: Measurement, status: TrialStatus = TrialStatus.measured) -> Trial:
    return Trial(hypothesis_id="h1", round=1, status=status, measurements=rows)


def hypothesis(change_class: ChangeClass = ChangeClass.efficiency) -> Hypothesis:
    return Hypothesis(
        id="h1", project_id=P, source=HypothesisSource.playbook, title="t",
        rationale="r", change_class=change_class, expected_gain=0.1,
        provability=0.5, risk=0.1,
    )  # fmt: skip


# ---------------------------------------------------------------------------
# The fit
# ---------------------------------------------------------------------------


def test_the_growth_rate_is_the_log_log_slope() -> None:
    assert growth_rate(((10, 1.0), (40, 16.0))) == pytest.approx(2.0)
    assert growth_rate(((10, 3.0), (20, 3.0), (40, 3.0))) == pytest.approx(0.0)
    assert growth_rate(((1, 1.0), (2, 2.0), (4, 4.0))) == pytest.approx(1.0)
    # least squares over three points: ln t = 0, 1.5 ln 2, 2 ln 2 against ln n = 0, ln 2, 2 ln 2
    assert growth_rate(((1, 1.0), (2, 2**1.5), (4, 4.0))) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# What the judge records
# ---------------------------------------------------------------------------


def test_the_judge_is_a_frozen_shadow_judge_that_applies_to_every_objective() -> None:
    judge = ScalingJudge()

    assert isinstance(judge, Judge)
    assert judge.name == SCALING_JUDGE == "scaling"
    assert SHADOW_JUDGES == frozenset({OP_COUNT_JUDGE, SCALING_JUDGE})
    assert judge.applies_to(OBJECTIVE)
    with pytest.raises(AttributeError):
        judge.name = "x"  # type: ignore[misc]


def test_a_quadratic_to_linear_change_records_rates_two_and_one() -> None:
    """
    GIVEN a base growing as n^2 and a trial growing as n over three sizes
    WHEN judged
    THEN the base rate 2, the trial rate 1, the change -1 and the tolerance
        are recorded, the growth is not the same; the outcome is still
        not_applicable (records only)
    """
    result = ScalingJudge().evaluate(
        baseline(*grows(W1, 2), wall(W1, 1.0)), trial(*grows(W1, 1, 1e-5, trial_id="t"))
    )

    assert result.outcome is JudgeOutcome.not_applicable
    assert result.metric == METRIC_SCALE_WALL_S
    assert result.gain is None and result.noise_floor is None and result.output_changed is None  # fmt: skip
    assert result.baseline is not None and result.trial is not None
    assert result.baseline.mean == pytest.approx(2.0) and result.baseline.unit == "rate"
    assert result.trial.mean == pytest.approx(1.0)
    assert result.details == {
        "shadow": True,
        "workloads": 1,
        "unscaled": 0,
        "base_rate": pytest.approx(2.0),
        "trial_rate": pytest.approx(1.0),
        "change": pytest.approx(-1.0),
        "largest_change": pytest.approx(-1.0),
        "tolerance": GROWTH_TOLERANCE,
        "same_growth": False,
    }
    assert result.reason == (
        "shadow, records only: growth rate 1.00 against the base's 2.00 (-1.00)"
        " over 1 workload(s)"
    )


def test_a_constant_factor_speed_up_records_the_same_growth() -> None:
    result = ScalingJudge().evaluate(
        baseline(*grows(W1, 2)), trial(*grows(W1, 2, 1e-8 / 5))
    )

    assert result.details["change"] == pytest.approx(0.0, abs=1e-9)
    assert result.details["same_growth"] is True
    assert "(+0.00)" in result.reason


def test_identical_rows_record_exactly_no_change() -> None:
    rows = grows(W1, 1.3)

    result = ScalingJudge().evaluate(baseline(*rows), trial(*rows))

    assert result.details["change"] == 0.0 and result.details["same_growth"] is True


def test_the_median_of_each_size_is_fitted_so_one_slow_run_moves_nothing() -> None:
    base = (at(W1, 100, 1.0, 1.0, 9.0), at(W1, 400, 4.0, 40.0, 4.0))

    result = ScalingJudge().evaluate(baseline(*base), trial(*grows(W1, 1, 0.01, (100, 400))))  # fmt: skip

    assert result.details["base_rate"] == pytest.approx(1.0)
    assert result.details["change"] == pytest.approx(0.0, abs=1e-9)


def test_two_workloads_record_the_mean_rates_and_the_largest_change() -> None:
    """W1 goes from n^2 to n, W2 stays at n: the means are recorded, the
    largest change is W1's, and the growth is not the same."""
    base = baseline(*grows(W1, 2), *grows(W2, 1))
    after = trial(*grows(W1, 1), *grows(W2, 1, 2e-8))

    result = ScalingJudge().evaluate(base, after)

    assert result.details["workloads"] == 2
    assert result.details["base_rate"] == pytest.approx(1.5)
    assert result.details["trial_rate"] == pytest.approx(1.0)
    assert result.details["change"] == pytest.approx(-0.5)
    assert result.details["largest_change"] == pytest.approx(-1.0)
    assert result.details["same_growth"] is False
    assert result.baseline is not None and result.baseline.n == 2


def test_the_fit_uses_only_the_sizes_both_sides_ran() -> None:
    """The trial lacks the largest size: both fit over the two shared ones."""
    base = (*grows(W1, 2, sizes=(1000, 2000)), at(W1, 4000, 1e9))

    result = ScalingJudge().evaluate(baseline(*base), trial(*grows(W1, 2, sizes=(1000, 2000))))  # fmt: skip

    assert result.details["base_rate"] == pytest.approx(2.0)
    assert result.details["same_growth"] is True


@pytest.mark.parametrize(
    "rows",
    [
        (),  # nothing scaled: the workload had no size setting
        grows(W1, 1, sizes=(1000,)),  # one shared size fits nothing
        (at(W1, 1000, 1.0), at(W1, 4000, 0.0)),  # no log of a zero time
        (at(W1, True, 1.0), at(W1, 4000, 1.0)),  # a size that is not an int
        (at(W1, 0, 1.0), at(W1, 4000, 1.0)),  # nor a positive one
        (at(W1, "1000", 1.0), at(W1, 4000, 1.0)),
    ],
)
def test_a_workload_with_no_usable_scaling_on_both_sides_records_nothing(
    rows: tuple[Measurement, ...],
) -> None:
    base = baseline(*grows(W1, 2), wall(W1, 1.0))

    result = ScalingJudge().evaluate(base, trial(*rows, wall(W1, 1.0)))

    assert result.outcome is JudgeOutcome.not_applicable
    assert result.baseline is None and result.trial is None and result.metric is None
    assert result.details == {"shadow": True, "workloads": 0, "unscaled": 1}
    assert result.reason == "shadow, records only: no scaling runs on both sides"


def test_no_size_setting_anywhere_records_no_workload_at_all() -> None:
    result = ScalingJudge().evaluate(baseline(wall(W1, 1.0)), trial(wall(W1, 0.5)))

    assert result.details == {"shadow": True, "workloads": 0, "unscaled": 0}


def test_a_workload_scaled_on_one_side_only_is_left_out_and_counted_as_such() -> None:
    result = ScalingJudge().evaluate(
        baseline(*grows(W1, 2), *grows(W2, 2)), trial(*grows(W1, 2))
    )

    assert (result.details["workloads"], result.details["unscaled"]) == (1, 1)
    assert result.reason.endswith("over 1 workload(s); 1 not scaled on both sides")


def test_a_repeated_size_row_is_read_once_first_wins() -> None:
    """Rows a runner repeats (or forges) change nothing beyond the first."""
    base = (*grows(W1, 2), at(W1, 4000, 1e-9))

    result = ScalingJudge().evaluate(baseline(*base), trial(*grows(W1, 2)))

    assert result.details["base_rate"] == pytest.approx(2.0)


def test_default_judges_hold_it_only_when_asked_and_last() -> None:
    plain = default_judges()

    assert all(not isinstance(j, ScalingJudge) for j in plain)
    assert default_judges(scaling=True) == (*plain, ScalingJudge())
    assert default_judges(op_count=True, scaling=True) == (*plain, OpCountJudge(), ScalingJudge())  # fmt: skip


# ---------------------------------------------------------------------------
# It never decides: the verdict with and without it
# ---------------------------------------------------------------------------


def _shape(verdict: Verdict) -> tuple[object, ...]:
    """Everything a verdict decides (its id, time and judge list aside)."""
    return (
        verdict.outcome, verdict.summary, verdict.gain, verdict.change_class,
        verdict.violations, verdict.trial_id, verdict.hypothesis_id,
    )  # fmt: skip


BASE = baseline(wall(W1, 1.0), tests_row(W1), *grows(W1, 2))
LINEAR, SAME = grows(W1, 1, 1e-5), grows(W1, 2, 5e-9)
SCENARIOS = {
    "keep, better growth": (trial(wall(W1, 0.8), tests_row(W1), *LINEAR), ChangeClass.efficiency, ()),
    "keep, same growth": (trial(wall(W1, 0.8), tests_row(W1), *SAME), ChangeClass.efficiency, ()),
    "keep, worse growth": (trial(wall(W1, 0.8), tests_row(W1), *grows(W1, 3)), ChangeClass.efficiency, ()),
    "inconclusive, better growth": (trial(wall(W1, 0.995), tests_row(W1), *LINEAR), ChangeClass.efficiency, ()),
    "regressed, better growth": (trial(wall(W1, 1.3), tests_row(W1), *LINEAR), ChangeClass.efficiency, ()),
    "tests fail": (trial(wall(W1, 0.8), tests_row(W1, 0.0), *LINEAR), ChangeClass.efficiency, ()),
    "behaviour": (trial(wall(W1, 0.8), tests_row(W1), *LINEAR), ChangeClass.behaviour, ()),
    "novel": (trial(wall(W1, 0.8), tests_row(W1), *LINEAR), ChangeClass.novel, ()),
    "failed trial": (trial(status=TrialStatus.failed), ChangeClass.efficiency, ()),
    "not scaled": (trial(wall(W1, 0.8), tests_row(W1)), ChangeClass.efficiency, ()),
    "violation": (
        trial(wall(W1, 0.8), tests_row(W1), *LINEAR), ChangeClass.efficiency,
        (Violation(rule=ViolationRule.protected_path, path="tests/x.py", message="m"),),
    ),
}  # fmt: skip


@pytest.mark.parametrize("name", list(SCENARIOS))
@pytest.mark.parametrize("primary", [None, METRIC_WALL_TIME_S])
def test_the_verdict_is_the_same_with_and_without_the_judge(
    name: str, primary: str | None
) -> None:
    """
    GIVEN keeps with better, the same and worse growth, an inconclusive and a
        regressed timing result with better growth, failing tests, every
        change class, a failed trial, an unscaled trial and a violation
    WHEN the verdict is derived from the default judges, then from the
        default judges plus the scaling judge
    THEN outcome, summary, gain and everything else a verdict decides are
        identical; the second verdict lists the shadow result, last
    """
    after, change_class, violations = SCENARIOS[name]
    results = tuple(j.evaluate(BASE, after) for j in default_judges())
    shadow = ScalingJudge().evaluate(BASE, after)

    without = derive_verdict(after, hypothesis(change_class), results, violations, primary_metric=primary)  # fmt: skip
    with_it = derive_verdict(after, hypothesis(change_class), (*results, shadow), violations, primary_metric=primary)  # fmt: skip

    assert _shape(with_it) == _shape(without)
    assert with_it.judge_results == (*results, shadow)


FORGED = [
    JudgeResult(
        judge=SCALING_JUDGE, outcome=outcome, metric=metric, gain=gain, reason="forged",
        output_changed=changed,
    )  # fmt: skip
    for outcome, metric, gain, changed in itertools.product(
        JudgeOutcome, (None, METRIC_SCALE_WALL_S, METRIC_WALL_TIME_S), (None, 0.9), (None, True)
    )
]  # fmt: skip


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_no_result_under_the_judges_name_can_change_a_verdict(name: str) -> None:
    """Whatever a scaling result says (passed, failed, inconclusive, a gain,
    the timing judge's metric, an output change), placed first or last, the
    verdict is the one without it: shadow results never decide."""
    after, change_class, violations = SCENARIOS[name]
    results = tuple(j.evaluate(BASE, after) for j in default_judges())
    without = _shape(derive_verdict(after, hypothesis(change_class), results, violations, primary_metric=METRIC_WALL_TIME_S))  # fmt: skip

    for forged in FORGED:
        for ordered in ((forged, *results), (*results, forged)):
            verdict = derive_verdict(after, hypothesis(change_class), ordered, violations, primary_metric=METRIC_WALL_TIME_S)  # fmt: skip
            assert _shape(verdict) == without, forged


def test_the_rates_are_finite_numbers_a_report_can_print() -> None:
    result = ScalingJudge().evaluate(baseline(*grows(W1, 2)), trial(*grows(W1, 0.5)))

    rates = (result.details["base_rate"], result.details["trial_rate"])
    assert all(isinstance(r, float) and math.isfinite(r) for r in rates)
