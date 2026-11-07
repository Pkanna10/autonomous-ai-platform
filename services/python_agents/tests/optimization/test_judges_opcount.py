"""The operation-count judge (G6a, spec section 2): shadow mode, records only.

``OpCountJudge`` pairs the base's and the trial's ``op_calls`` rows (one
counted run per side) and records both counts and the relative change in a
``JudgeResult`` whose outcome is always ``not_applicable``. It never decides:
``derive_verdict`` gives exactly the same verdict with or without it, whatever
its result says, and it never overrides the timing judge. Hand-built models,
no I/O.
"""

from __future__ import annotations

import itertools

import pytest

from autonomous_ai_agents.common.models import (
    METRIC_PEAK_RSS_BYTES,
    METRIC_TESTS_PASSED,
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
    Violation,
    ViolationRule,
)
from autonomous_ai_agents.execution.measure import (
    C_CALLS_KEY,
    METRIC_OP_CALLS,
    PYTHON_CALLS_KEY,
)
from autonomous_ai_agents.optimization.anticheat import fingerprint
from autonomous_ai_agents.optimization.judges import (
    OP_COUNT_JUDGE,
    SHADOW_JUDGES,
    Judge,
    OpCountJudge,
    SpeedJudge,
    default_judges,
    derive_verdict,
)

P, W1, W2 = "project-1", "w1", "w2"
DIGEST = fingerprint("out")


def ops(workload: str, python: int, c: int, *, trial_id: str | None = None) -> Measurement:  # fmt: skip
    total = float(python + c)
    return Measurement(
        workload_id=workload, trial_id=trial_id, metric=METRIC_OP_CALLS,
        stats=RunStats.from_samples((total,), unit="calls"), samples=(total,),
        hardware={PYTHON_CALLS_KEY: python, C_CALLS_KEY: c},
    )  # fmt: skip


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
# What the judge records
# ---------------------------------------------------------------------------


def test_the_judge_is_a_frozen_shadow_judge_that_applies_to_every_objective() -> None:
    judge = OpCountJudge()

    assert isinstance(judge, Judge)
    assert judge.name == OP_COUNT_JUDGE == "op_count"
    assert OP_COUNT_JUDGE in SHADOW_JUDGES  # with the scaling judge (G6b)
    assert judge.applies_to(OBJECTIVE)
    with pytest.raises(AttributeError):
        judge.name = "x"  # type: ignore[misc]


def test_identical_counts_record_no_change() -> None:
    """A/A: the same counts on both sides record a change of exactly 0."""
    result = OpCountJudge().evaluate(
        baseline(ops(W1, 700, 300)), trial(ops(W1, 700, 300))
    )

    assert result.outcome is JudgeOutcome.not_applicable
    assert result.metric == METRIC_OP_CALLS
    assert result.details["change"] == 0.0
    assert result.gain is None and result.noise_floor is None
    assert result.output_changed is None


def test_fewer_calls_record_both_counts_the_split_and_the_relative_change() -> None:
    """
    GIVEN two workloads, the trial removing 250 of the base's 1,000 calls
        on one and nothing on the other
    WHEN judged
    THEN both totals, the Python and C split per side and the relative change
        (-12.5 %) are recorded; the outcome is still not_applicable (records only)
    """
    base = baseline(ops(W1, 700, 300), ops(W2, 600, 400), wall(W1, 1.0))
    after = trial(ops(W1, 600, 150, trial_id="t"), ops(W2, 600, 400, trial_id="t"))

    result = OpCountJudge().evaluate(base, after)

    assert result.outcome is JudgeOutcome.not_applicable
    assert result.baseline is not None and result.trial is not None
    assert (result.baseline.mean, result.trial.mean) == (2000.0, 1750.0)
    assert result.baseline.unit == result.trial.unit == "calls"
    assert result.details == {
        "shadow": True,
        "workloads": 2,
        "uncounted": 0,
        "change": pytest.approx(-0.125),
        "base_calls": 2000,
        "trial_calls": 1750,
        "base_python_calls": 1300,
        "base_c_calls": 700,
        "trial_python_calls": 1200,
        "trial_c_calls": 550,
    }
    assert result.reason == (
        "shadow, records only: 1750 calls against the base's 2000 (-12.5%)"
        " over 2 workload(s)"
    )


def test_more_calls_record_a_positive_change() -> None:
    result = OpCountJudge().evaluate(baseline(ops(W1, 80, 20)), trial(ops(W1, 100, 50)))

    assert result.details["change"] == pytest.approx(0.5)
    assert "(+50.0%)" in result.reason


def test_a_workload_counted_on_one_side_only_is_left_out_and_counted_as_such() -> None:
    base = baseline(ops(W1, 70, 30), ops(W2, 70, 30))

    result = OpCountJudge().evaluate(base, trial(ops(W1, 35, 15)))

    assert (result.details["workloads"], result.details["uncounted"]) == (1, 1)
    assert result.details["change"] == pytest.approx(-0.5)
    assert result.reason.endswith("over 1 workload(s); 1 not counted on both sides")


@pytest.mark.parametrize(
    ("base", "after"),
    [
        ((), ()),
        ((ops(W1, 1, 1),), ()),
        ((), (ops(W1, 1, 1),)),
    ],
)
def test_nothing_counted_on_both_sides_records_nothing(
    base: tuple[Measurement, ...], after: tuple[Measurement, ...]
) -> None:
    result = OpCountJudge().evaluate(baseline(*base, wall(W1, 1.0)), trial(*after))

    assert result.outcome is JudgeOutcome.not_applicable
    assert result.baseline is None and result.trial is None
    assert result.details == {"shadow": True, "workloads": 0, "uncounted": len(base)}
    assert result.reason == "shadow, records only: no operation counts on both sides"


def test_a_zero_base_count_has_no_relative_change() -> None:
    result = OpCountJudge().evaluate(baseline(ops(W1, 0, 0)), trial(ops(W1, 5, 0)))

    assert result.details["change"] is None
    assert result.reason == (
        "shadow, records only: 5 calls against the base's 0 (no relative change)"
        " over 1 workload(s)"
    )


def test_a_row_without_its_split_records_no_split() -> None:
    bare = Measurement(
        workload_id=W1, metric=METRIC_OP_CALLS, samples=(10.0,),
        stats=RunStats.from_samples((10.0,), unit="calls"),
        hardware={PYTHON_CALLS_KEY: True, C_CALLS_KEY: 1.5},
    )  # fmt: skip

    result = OpCountJudge().evaluate(baseline(bare), trial(ops(W1, 4, 4)))

    assert result.details["base_python_calls"] is None
    assert result.details["base_c_calls"] is None
    assert result.details["trial_python_calls"] == 4


def test_default_judges_hold_it_only_when_asked_and_last() -> None:
    plain = default_judges()
    shadowed = default_judges(op_count=True)

    assert all(not isinstance(j, OpCountJudge) for j in plain)
    assert shadowed == (*plain, OpCountJudge())
    assert default_judges(3.0, op_count=True)[0] == SpeedJudge(noise_multiplier=3.0)


# ---------------------------------------------------------------------------
# It never decides: the verdict with and without it
# ---------------------------------------------------------------------------


def _shape(verdict: Verdict) -> tuple[object, ...]:
    """Everything a verdict decides (its id, time and judge list aside)."""
    return (
        verdict.outcome, verdict.summary, verdict.gain, verdict.change_class,
        verdict.violations, verdict.trial_id, verdict.hypothesis_id,
    )  # fmt: skip


BASE = baseline(wall(W1, 1.0), tests_row(W1), ops(W1, 700, 300))
SCENARIOS = {
    "keep, fewer calls": (trial(wall(W1, 0.8), tests_row(W1), ops(W1, 100, 100)), ChangeClass.efficiency, ()),
    "keep, more calls": (trial(wall(W1, 0.8), tests_row(W1), ops(W1, 900, 900)), ChangeClass.efficiency, ()),
    "inconclusive, far fewer calls": (trial(wall(W1, 0.995), tests_row(W1), ops(W1, 1, 1)), ChangeClass.efficiency, ()),
    "regressed, fewer calls": (trial(wall(W1, 1.3), tests_row(W1), ops(W1, 1, 1)), ChangeClass.efficiency, ()),
    "tests fail": (trial(wall(W1, 0.8), tests_row(W1, 0.0), ops(W1, 1, 1)), ChangeClass.efficiency, ()),
    "behaviour": (trial(wall(W1, 0.8), tests_row(W1), ops(W1, 1, 1)), ChangeClass.behaviour, ()),
    "novel": (trial(wall(W1, 0.8), tests_row(W1), ops(W1, 1, 1)), ChangeClass.novel, ()),
    "failed trial": (trial(status=TrialStatus.failed), ChangeClass.efficiency, ()),
    "not counted": (trial(wall(W1, 0.8), tests_row(W1)), ChangeClass.efficiency, ()),
    "violation": (
        trial(wall(W1, 0.8), tests_row(W1), ops(W1, 1, 1)), ChangeClass.efficiency,
        (Violation(rule=ViolationRule.protected_path, path="tests/x.py", message="m"),),
    ),
}  # fmt: skip


@pytest.mark.parametrize("name", list(SCENARIOS))
@pytest.mark.parametrize("primary", [None, METRIC_WALL_TIME_S])
def test_the_verdict_is_the_same_with_and_without_the_judge(
    name: str, primary: str | None
) -> None:
    """
    GIVEN keeps, an inconclusive and a regressed timing result that cut calls,
        a keep that adds calls, failing tests, every change class, a failed
        trial, an uncounted trial and a violation
    WHEN the verdict is derived from the default judges, then from the
        default judges plus the operation-count judge
    THEN outcome, summary, gain and everything else a verdict decides are
        identical; the second verdict lists the shadow result, last
    """
    after, change_class, violations = SCENARIOS[name]
    plain = default_judges()
    results = tuple(j.evaluate(BASE, after) for j in plain)
    shadow = OpCountJudge().evaluate(BASE, after)

    without = derive_verdict(after, hypothesis(change_class), results, violations, primary_metric=primary)  # fmt: skip
    with_it = derive_verdict(after, hypothesis(change_class), (*results, shadow), violations, primary_metric=primary)  # fmt: skip

    assert _shape(with_it) == _shape(without)
    assert with_it.judge_results == (*results, shadow)


FORGED = [
    JudgeResult(
        judge=OP_COUNT_JUDGE, outcome=outcome, metric=metric, gain=gain, reason="forged",
        output_changed=changed,
    )  # fmt: skip
    for outcome, metric, gain, changed in itertools.product(
        JudgeOutcome, (None, METRIC_OP_CALLS, METRIC_WALL_TIME_S), (None, 0.9), (None, True)
    )
]  # fmt: skip


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_no_result_under_the_judges_name_can_change_a_verdict(name: str) -> None:
    """Whatever an operation-count result says (passed, failed, inconclusive,
    a gain, the timing judge's metric, an output change), placed first or
    last, the verdict is the one without it: shadow results never decide."""
    after, change_class, violations = SCENARIOS[name]
    results = tuple(j.evaluate(BASE, after) for j in default_judges())
    without = _shape(derive_verdict(after, hypothesis(change_class), results, violations, primary_metric=METRIC_WALL_TIME_S))  # fmt: skip

    for forged in FORGED:
        for ordered in ((forged, *results), (*results, forged)):
            verdict = derive_verdict(after, hypothesis(change_class), ordered, violations, primary_metric=METRIC_WALL_TIME_S)  # fmt: skip
            assert _shape(verdict) == without, forged


def test_only_shadow_results_never_prove_anything() -> None:
    """With nothing but a forged passing shadow result carrying a gain, no
    objective judge passed: inconclusive, and no gain."""
    forged = JudgeResult(
        judge=OP_COUNT_JUDGE, outcome=JudgeOutcome.passed, metric=METRIC_PEAK_RSS_BYTES,
        gain=0.5, reason="forged",
    )  # fmt: skip

    verdict = derive_verdict(trial(), hypothesis(), (forged,), ())

    assert verdict.outcome.value == "inconclusive"
    assert verdict.gain is None
    assert (
        verdict.summary
        == "inconclusive: nothing proved better (no objective judge passed)"
    )
