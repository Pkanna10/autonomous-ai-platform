"""Judges: frozen evaluators that decide whether a trial proved itself better.

A judge pairs the baseline's measurements with the trial's per workload and
reports one :class:`JudgeResult`. Judges are frozen dataclasses held in the
node context, never in the graph state, so nothing a trial writes can change
how that trial is judged. They do no I/O: every number they look at was
measured by the runner before they run.

Outcome semantics shared by every judge:

- ``passed``: the property was proven (gain beyond noise, bound respected...).
- ``failed``: the trial made things worse in a way the data proves.
- ``inconclusive``: the data cannot decide (inside the noise floor, a
  measurement missing, nothing to compare).
- ``not_applicable``: no objective or guardrail asks this judge's question.

:func:`derive_verdict` then folds the judge results and the anti-cheating
violations into one :class:`Verdict`, in a fixed order.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

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
    JudgeOutcome,
    JudgeResult,
    Measurement,
    NoiseCheck,
    Objective,
    RunStats,
    ScalarDict,
    Trial,
    TrialStatus,
    Verdict,
    VerdictOutcome,
    Violation,
)
from autonomous_ai_agents.optimization.anticheat import (
    compare_fingerprints,
    exceeds_noise,
    relative_gain,
)


@runtime_checkable
class Judge(Protocol):
    """A frozen evaluator of one property of a trial against the baseline."""

    @property
    def name(self) -> str: ...

    def applies_to(self, objective: Objective) -> bool: ...

    def evaluate(self, baseline: Baseline, trial: Trial) -> JudgeResult: ...


# ---------------------------------------------------------------------------
# Measurement pairing helpers
# ---------------------------------------------------------------------------


def _by_workload(
    measurements: Sequence[Measurement], metric: str
) -> dict[str, Measurement]:
    """First measurement of ``metric`` per workload, in measurement order."""
    seen: dict[str, Measurement] = {}
    for measurement in measurements:
        if measurement.metric == metric:
            seen.setdefault(measurement.workload_id, measurement)
    return seen


def _pair(
    baseline: Sequence[Measurement], trial: Sequence[Measurement], metric: str
) -> list[tuple[str, Measurement, Measurement | None]]:
    """Pair baseline and trial measurements of ``metric`` by workload.

    Every workload the baseline measured appears once; the trial side is
    ``None`` when the trial has no measurement of that metric for it.
    """
    actual = _by_workload(trial, metric)
    return [
        (workload_id, measurement, actual.get(workload_id))
        for workload_id, measurement in _by_workload(baseline, metric).items()
    ]


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


# ---------------------------------------------------------------------------
# Gain judges: speed, memory and any other objective metric
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _GainCheck:
    workload_id: str
    baseline: RunStats
    trial: RunStats
    check: NoiseCheck

    @property
    def regressed(self) -> bool:
        """True when the trial got worse by more than the noise floor."""
        return self.check.gain_abs < -self.check.floor_abs


@dataclass(frozen=True)
class MetricGainJudge:
    """Passes when the trial improves ``metric`` by more than the noise floor.

    The objective for the metric (direction, minimum relative gain) is read
    from the baseline. Every workload the baseline measured must clear the
    floor; the result reports the weakest workload.
    """

    metric: str
    noise_multiplier: float = 2.0

    @property
    def name(self) -> str:
        """Judge name as it appears in results."""
        return f"gain:{self.metric}"

    def applies_to(self, objective: Objective) -> bool:
        """True when the objective targets this judge's metric."""
        return objective.metric == self.metric

    def evaluate(self, baseline: Baseline, trial: Trial) -> JudgeResult:
        """Compare trial and baseline measurements of the metric per workload."""
        objective = next(
            (o for o in baseline.objectives if o.metric == self.metric), None
        )
        if objective is None:
            return self._result(
                JudgeOutcome.not_applicable,
                reason=f"no objective targets {self.metric}",
                details={"workloads": 0},
            )
        pairs = _pair(baseline.measurements, trial.measurements, self.metric)
        details: ScalarDict = {"workloads": len(pairs)}
        if not pairs:
            return self._result(
                JudgeOutcome.inconclusive,
                reason=f"no baseline measurement for metric {self.metric}",
                details=details,
            )

        checks: list[_GainCheck] = []
        missing: list[tuple[str, Measurement]] = []
        for workload_id, expected, actual in pairs:
            if actual is None:
                missing.append((workload_id, expected))
                continue
            check = exceeds_noise(
                expected.stats,
                actual.stats,
                objective.direction,
                objective.min_relative_gain,
                self.noise_multiplier,
            )
            checks.append(_GainCheck(workload_id, expected.stats, actual.stats, check))

        regressions = [c for c in checks if c.regressed]
        if regressions:
            culprit = min(regressions, key=lambda c: c.check.gain_rel)
            worst = min(checks, key=lambda c: c.check.gain_rel)
            return self._result(
                JudgeOutcome.failed,
                reason=(
                    f"{self.metric} regressed {_percent(-culprit.check.gain_rel)} "
                    f"beyond the noise floor {_percent(culprit.check.floor_rel)} "
                    f"(workload {culprit.workload_id})"
                ),
                details=details,
                worst=worst,
            )
        if missing:
            workload_id, expected = missing[0]
            return self._result(
                JudgeOutcome.inconclusive,
                reason=(
                    f"no trial measurement for metric {self.metric} "
                    f"(workload {workload_id})"
                ),
                details=details,
                baseline=expected.stats,
            )
        worst = min(checks, key=lambda c: c.check.gain_rel)
        if not worst.check.passed:
            return self._result(
                JudgeOutcome.inconclusive,
                reason=(
                    f"{self.metric} gain {_percent(worst.check.gain_rel)} is inside "
                    f"the noise floor {_percent(worst.check.floor_rel)} "
                    f"(workload {worst.workload_id})"
                ),
                details=details,
                worst=worst,
            )
        return self._result(
            JudgeOutcome.passed,
            reason=(
                f"{self.metric} improved {_percent(worst.check.gain_rel)} "
                f"(noise floor {_percent(worst.check.floor_rel)}) "
                f"across {len(checks)} workload(s)"
            ),
            details=details,
            worst=worst,
        )

    def _result(
        self,
        outcome: JudgeOutcome,
        *,
        reason: str,
        details: ScalarDict,
        worst: _GainCheck | None = None,
        baseline: RunStats | None = None,
    ) -> JudgeResult:
        if worst is not None:
            return JudgeResult(
                judge=self.name,
                outcome=outcome,
                metric=self.metric,
                baseline=worst.baseline,
                trial=worst.trial,
                gain=worst.check.gain_rel,
                noise_floor=worst.check.floor_rel,
                reason=reason,
                details=details,
            )
        return JudgeResult(
            judge=self.name,
            outcome=outcome,
            metric=self.metric,
            baseline=baseline,
            reason=reason,
            details=details,
        )


@dataclass(frozen=True)
class SpeedJudge(MetricGainJudge):
    """Wall-clock time must drop by more than the noise floor."""

    metric: str = METRIC_WALL_TIME_S

    @property
    def name(self) -> str:
        """Judge name as it appears in results."""
        return "speed"


@dataclass(frozen=True)
class MemoryJudge(MetricGainJudge):
    """Peak resident memory must drop by more than the noise floor."""

    metric: str = METRIC_PEAK_RSS_BYTES

    @property
    def name(self) -> str:
        """Judge name as it appears in results."""
        return "memory"


# ---------------------------------------------------------------------------
# Equivalence judge: outputs must not change
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EquivalenceJudge:
    """Output fingerprints must match the baseline's for every workload."""

    @property
    def name(self) -> str:
        """Judge name as it appears in results."""
        return "equivalence"

    def applies_to(self, objective: Objective) -> bool:
        """Outputs must stay equivalent whatever the objective is."""
        return True

    def evaluate(self, baseline: Baseline, trial: Trial) -> JudgeResult:
        """Compare output fingerprints per workload when the guardrail asks for it."""
        if not any(
            g.kind is GuardrailKind.output_equivalence for g in baseline.guardrails
        ):
            return JudgeResult(
                judge=self.name,
                outcome=JudgeOutcome.not_applicable,
                reason="no output_equivalence guardrail",
                details={"workloads": 0},
            )
        workloads = len({m.workload_id for m in baseline.measurements})
        details: ScalarDict = {"workloads": workloads}
        if workloads == 0:
            return JudgeResult(
                judge=self.name,
                outcome=JudgeOutcome.inconclusive,
                reason="no baseline measurements to compare outputs against",
                details=details,
            )
        violations = compare_fingerprints(baseline.measurements, trial.measurements)
        if violations:
            return JudgeResult(
                judge=self.name,
                outcome=JudgeOutcome.failed,
                reason="; ".join(v.message for v in violations),
                details=details,
            )
        return JudgeResult(
            judge=self.name,
            outcome=JudgeOutcome.passed,
            reason=f"outputs identical for {workloads} workload(s)",
            details=details,
        )


# ---------------------------------------------------------------------------
# Guardrail metric judge: bounded drops
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Drop:
    metric: str
    max_drop: float
    workload_id: str
    baseline: RunStats
    trial: RunStats
    drop: float

    @property
    def breached(self) -> bool:
        """True when the drop is strictly beyond the bound."""
        return self.drop > self.max_drop and not math.isclose(
            self.drop, self.max_drop, rel_tol=1e-9, abs_tol=1e-12
        )


def _bound_fields(guardrail: Guardrail) -> tuple[str, Direction, float]:
    """Return (metric, direction, max_drop) of a metric_bound guardrail."""
    if (
        guardrail.metric is None
        or guardrail.direction is None
        or guardrail.max_drop is None
    ):
        raise ValueError(f"metric_bound guardrail {guardrail.id} is incomplete")
    return guardrail.metric, guardrail.direction, guardrail.max_drop


@dataclass(frozen=True)
class GuardrailMetricJudge:
    """Every ``metric_bound`` guardrail's metric may drop at most ``max_drop``.

    The drop is relative to the baseline mean and signed so that a negative
    drop is an improvement; the result's gain is minus the worst drop.
    """

    @property
    def name(self) -> str:
        """Judge name as it appears in results."""
        return "guardrail"

    def applies_to(self, objective: Objective) -> bool:
        """Guardrails hold whatever the objective is."""
        return True

    def evaluate(self, baseline: Baseline, trial: Trial) -> JudgeResult:
        """Check every bounded metric on every workload."""
        bounds = [
            g for g in baseline.guardrails if g.kind is GuardrailKind.metric_bound
        ]
        if not bounds:
            return JudgeResult(
                judge=self.name,
                outcome=JudgeOutcome.not_applicable,
                reason="no metric_bound guardrail",
                details={"guardrails": 0},
            )
        drops: list[_Drop] = []
        missing: list[str] = []
        for guardrail in bounds:
            metric, direction, max_drop = _bound_fields(guardrail)
            pairs = _pair(baseline.measurements, trial.measurements, metric)
            if not pairs:
                missing.append(f"no baseline measurement for {metric}")
            for workload_id, expected, actual in pairs:
                if actual is None:
                    missing.append(
                        f"no trial measurement for {metric} (workload {workload_id})"
                    )
                    continue
                try:
                    drop = -relative_gain(expected.stats, actual.stats, direction)
                except ValueError:
                    missing.append(
                        f"baseline mean of {metric} is zero (workload {workload_id})"
                    )
                    continue
                drops.append(
                    _Drop(
                        metric,
                        max_drop,
                        workload_id,
                        expected.stats,
                        actual.stats,
                        drop,
                    )
                )

        breaches = [d for d in drops if d.breached]
        if breaches:
            worst = max(breaches, key=lambda d: d.drop)
            return self._result(
                JudgeOutcome.failed,
                reason=(
                    f"{worst.metric} dropped {_percent(worst.drop)}, more than the "
                    f"allowed {_percent(worst.max_drop)} (workload {worst.workload_id})"
                ),
                guardrails=len(bounds),
                worst=worst,
            )
        if missing:
            return self._result(
                JudgeOutcome.inconclusive,
                reason="; ".join(missing),
                guardrails=len(bounds),
            )
        worst = max(drops, key=lambda d: d.drop)
        return self._result(
            JudgeOutcome.passed,
            reason=(
                f"worst drop {_percent(worst.drop)} of {worst.metric} is within the "
                f"allowed {_percent(worst.max_drop)} (workload {worst.workload_id})"
            ),
            guardrails=len(bounds),
            worst=worst,
        )

    def _result(
        self,
        outcome: JudgeOutcome,
        *,
        reason: str,
        guardrails: int,
        worst: _Drop | None = None,
    ) -> JudgeResult:
        details: ScalarDict = {
            "guardrails": guardrails,
            "metric": None if worst is None else worst.metric,
            "max_drop": None if worst is None else worst.max_drop,
        }
        if worst is None:
            return JudgeResult(
                judge=self.name, outcome=outcome, reason=reason, details=details
            )
        return JudgeResult(
            judge=self.name,
            outcome=outcome,
            baseline=worst.baseline,
            trial=worst.trial,
            gain=-worst.drop,
            reason=reason,
            details=details,
        )


# ---------------------------------------------------------------------------
# Test-suite judge
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TestSuiteJudge:
    """The project's own test suite must pass on every run of the trial."""

    @property
    def name(self) -> str:
        """Judge name as it appears in results."""
        return "tests"

    def applies_to(self, objective: Objective) -> bool:
        """Tests must pass whatever the objective is."""
        return True

    def evaluate(self, baseline: Baseline, trial: Trial) -> JudgeResult:
        """Read the runner's ``tests_passed`` measurement(s) on the trial."""
        if not any(g.kind is GuardrailKind.tests_pass for g in baseline.guardrails):
            return JudgeResult(
                judge=self.name,
                outcome=JudgeOutcome.not_applicable,
                reason="no tests_pass guardrail",
                details={"workloads": 0},
            )
        runs = [m for m in trial.measurements if m.metric == METRIC_TESTS_PASSED]
        details: ScalarDict = {"workloads": len(runs)}
        if not runs:
            return JudgeResult(
                judge=self.name,
                outcome=JudgeOutcome.inconclusive,
                reason=f"no {METRIC_TESTS_PASSED} measurement on the trial",
                details=details,
            )
        failing = next((m for m in runs if not math.isclose(m.stats.mean, 1.0)), None)
        if failing is not None:
            return JudgeResult(
                judge=self.name,
                outcome=JudgeOutcome.failed,
                trial=failing.stats,
                reason=(
                    f"test suite failed (pass rate {_percent(failing.stats.mean)}, "
                    f"workload {failing.workload_id})"
                ),
                details=details,
            )
        return JudgeResult(
            judge=self.name,
            outcome=JudgeOutcome.passed,
            trial=runs[0].stats,
            reason=f"test suite passed on {len(runs)} workload(s)",
            details=details,
        )


def default_judges(noise_multiplier: float = 2.0) -> tuple[Judge, ...]:
    """The frozen judge set in evaluation order."""
    return (
        SpeedJudge(noise_multiplier=noise_multiplier),
        MemoryJudge(noise_multiplier=noise_multiplier),
        EquivalenceJudge(),
        GuardrailMetricJudge(),
        TestSuiteJudge(),
    )


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------


def primary_metric(objectives: Sequence[Objective]) -> str | None:
    """Metric of the highest-weight objective (the first one on ties)."""
    best: Objective | None = None
    for objective in objectives:
        if best is None or objective.weight > best.weight:
            best = objective
    return None if best is None else best.metric


def _select_gain(results: Sequence[JudgeResult], primary: str | None) -> float | None:
    """Gain of the passed primary-metric judge, else the first objective judge's."""
    objective_results = [r for r in results if r.metric is not None]
    if primary is not None:
        for result in objective_results:
            if result.metric == primary and result.outcome is JudgeOutcome.passed:
                return result.gain
    return next((r.gain for r in objective_results if r.gain is not None), None)


def _first(results: Sequence[JudgeResult], outcome: JudgeOutcome) -> JudgeResult | None:
    return next((r for r in results if r.outcome is outcome), None)


def derive_verdict(
    trial: Trial,
    hypothesis: Hypothesis,
    judge_results: Sequence[JudgeResult],
    violations: Sequence[Violation],
    *,
    primary_metric: str | None = None,
) -> Verdict:
    """Fold judge results and violations into a verdict, in a fixed order.

    1. any violation -> reject;
    2. trial failed or rejected -> reject;
    3. any judge failed -> reject;
    4. any judge inconclusive -> inconclusive;
    5. no objective judge (one carrying a metric) passed -> inconclusive;
    6. all passed: efficiency -> keep, behaviour or novel -> needs_approval.
    """
    results = tuple(judge_results)
    found = tuple(violations)
    change_class = hypothesis.change_class
    outcome, summary = _decide(trial, change_class, results, found)
    return Verdict(
        trial_id=trial.id,
        hypothesis_id=hypothesis.id,
        outcome=outcome,
        change_class=change_class,
        judge_results=results,
        violations=found,
        gain=_select_gain(results, primary_metric),
        summary=summary,
    )


def _decide(
    trial: Trial,
    change_class: ChangeClass,
    results: tuple[JudgeResult, ...],
    violations: tuple[Violation, ...],
) -> tuple[VerdictOutcome, str]:
    if violations:
        rules = ", ".join(dict.fromkeys(str(v.rule) for v in violations))
        return (
            VerdictOutcome.reject,
            f"reject: {len(violations)} anti-cheating violation(s): {rules}",
        )
    if trial.status in (TrialStatus.failed, TrialStatus.rejected):
        detail = f": {trial.error}" if trial.error else ""
        return VerdictOutcome.reject, f"reject: trial {trial.status}{detail}"
    failed = _first(results, JudgeOutcome.failed)
    if failed is not None:
        return (
            VerdictOutcome.reject,
            f"reject: judge {failed.judge} failed: {failed.reason}",
        )
    inconclusive = _first(results, JudgeOutcome.inconclusive)
    if inconclusive is not None:
        return (
            VerdictOutcome.inconclusive,
            f"inconclusive: judge {inconclusive.judge} inconclusive: "
            f"{inconclusive.reason}",
        )
    if not any(
        r.metric is not None and r.outcome is JudgeOutcome.passed for r in results
    ):
        return (
            VerdictOutcome.inconclusive,
            "inconclusive: nothing proved better (no objective judge passed)",
        )
    if change_class is ChangeClass.efficiency:
        return (
            VerdictOutcome.keep,
            "keep: all judges passed; efficiency change ships automatically",
        )
    return (
        VerdictOutcome.needs_approval,
        f"needs_approval: all judges passed; {change_class} change needs human approval",
    )
