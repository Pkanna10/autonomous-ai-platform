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

Shadow judges (``SHADOW_JUDGES``, spec section 2) record, never decide,
until the owner promotes them: :class:`OpCountJudge` (G6a) records the
operation counts of one counted run per side, :class:`ScalingJudge` (G6b)
how run time grows with input size on each side. ``derive_verdict`` leaves
their results out of every rule and of the gain, and keeps them on the
verdict for the report's column.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from autonomous_ai_agents.common.models import (
    METRIC_PEAK_RSS_BYTES,
    METRIC_TESTS_PASSED,
    METRIC_WALL_TIME_S,
    QUALITY_METRIC_PREFIX,
    Baseline,
    BuiltinMeasure,
    ChangeClass,
    Direction,
    DropUnit,
    Guardrail,
    GuardrailKind,
    Hypothesis,
    JudgeOutcome,
    JudgeResult,
    Measurement,
    NoiseCheck,
    Objective,
    QualityCheck,
    RunStats,
    ScalarDict,
    Trial,
    TrialStatus,
    Verdict,
    VerdictOutcome,
    Violation,
    ViolationRule,
)
from autonomous_ai_agents.execution.measure import (
    C_CALLS_KEY,
    METRIC_OP_CALLS,
    METRIC_SCALE_WALL_S,
    PYTHON_CALLS_KEY,
    SCALE_SIZE_KEY,
)
from autonomous_ai_agents.optimization.anticheat import (
    compare_fingerprints,
    exceeds_noise,
    proposal_conflict,
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
        unproven = [c for c in checks if not c.check.passed]
        if unproven:
            # Every workload must clear its own floor; report the one with the
            # thinnest margin, not merely the lowest gain.
            weakest = min(unproven, key=lambda c: c.check.gain_rel - c.check.floor_rel)
            return self._result(
                JudgeOutcome.inconclusive,
                reason=(
                    f"{self.metric} gain {_percent(weakest.check.gain_rel)} is inside "
                    f"the noise floor {_percent(weakest.check.floor_rel)} "
                    f"(workload {weakest.workload_id})"
                ),
                details=details,
                worst=weakest,
            )
        worst = min(checks, key=lambda c: c.check.gain_rel)
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


def _is_quality_bound(guardrail: Guardrail) -> bool:
    return guardrail.kind is GuardrailKind.metric_bound and (
        guardrail.metric or ""
    ).startswith(QUALITY_METRIC_PREFIX)


def _changed_workloads(
    baseline: Sequence[Measurement], trial: Sequence[Measurement]
) -> list[str]:
    """Workloads whose one agreed fingerprint differs between the two sides."""

    def digests(rows: Sequence[Measurement]) -> dict[str, set[str]]:
        seen: dict[str, set[str]] = {}
        for row in rows:
            bucket = seen.setdefault(row.workload_id, set())
            if row.output_fingerprint is not None:
                bucket.add(row.output_fingerprint)
        return seen

    before, after = digests(baseline), digests(trial)
    return [
        workload_id
        for workload_id, expected in before.items()
        if len(expected) == 1
        and len(actual := after.get(workload_id, set())) == 1
        and actual != expected
    ]


def _is_change_of(violation: Violation, changed: Sequence[str]) -> bool:
    """True for ``compare_fingerprints``' "output changed" on a changed workload.

    Matched by the exact message, never parsed: should that text ever
    change, a change stops matching and fails, which errs towards rejecting.
    """
    return violation.rule is ViolationRule.fingerprint_mismatch and any(
        violation.message == f"workload {workload_id}: output changed"
        for workload_id in changed
    )


@dataclass(frozen=True)
class EquivalenceJudge:
    """Output fingerprints must match the baseline's for every workload.

    Two modes (D35). *Exact*, under an ``output_equivalence`` guardrail: a
    changed, missing or unstable fingerprint fails. *Quality*, under a
    ``quality:<name>`` bound and no ``output_equivalence``: only a missing or
    unstable fingerprint fails (the output could not be scored once); a
    changed one passes with ``output_changed`` set, so rule 6 sends it to
    review and the guardrail judge decides on the quality number.
    """

    @property
    def name(self) -> str:
        """Judge name as it appears in results."""
        return "equivalence"

    def applies_to(self, objective: Objective) -> bool:
        """Outputs must stay equivalent whatever the objective is."""
        return True

    def evaluate(self, baseline: Baseline, trial: Trial) -> JudgeResult:
        """Compare output fingerprints per workload when a guardrail asks for it."""
        exact = any(
            g.kind is GuardrailKind.output_equivalence for g in baseline.guardrails
        )
        if not exact and not any(_is_quality_bound(g) for g in baseline.guardrails):
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
        changed = (
            []
            if exact
            else _changed_workloads(baseline.measurements, trial.measurements)
        )
        problems = [v for v in violations if not _is_change_of(v, changed)]
        if problems:
            return JudgeResult(
                judge=self.name,
                outcome=JudgeOutcome.failed,
                reason="; ".join(v.message for v in problems),
                details=details,
            )
        if exact:
            return JudgeResult(
                judge=self.name,
                outcome=JudgeOutcome.passed,
                reason=f"outputs identical for {workloads} workload(s)",
                details=details,
            )
        reason = (
            f"output changed on {len(changed)} of {workloads} workload(s): "
            f"{', '.join(changed)}; judged by the quality check"
            if changed
            else f"outputs identical for {workloads} workload(s)"
        )
        return JudgeResult(
            judge=self.name,
            outcome=JudgeOutcome.passed,
            reason=reason,
            details={**details, "changed": len(changed)},
            output_changed=bool(changed),
        )


# ---------------------------------------------------------------------------
# Guardrail metric judge: bounded drops
# ---------------------------------------------------------------------------


_POINT_MEASURES = frozenset(
    {BuiltinMeasure.accuracy, BuiltinMeasure.error_rate, BuiltinMeasure.macro_f1}
)
"""Builtins bounded in [0, 1]: an absolute drop of 0.005 reads "0.5 points"."""


def is_point_measure(measure: BuiltinMeasure | None) -> bool:
    """True for a builtin bounded in [0, 1]: its absolute drops (and D38
    labels) read in points, so 0.005 is "0.5 points"."""
    return measure in _POINT_MEASURES


_ZERO_TOL = 1e-12
"""Absolute tolerance for "on the bound" and "zero" in drops."""


def drop_text(value: float, unit: DropUnit, *, points: bool = False) -> str:
    """A drop in the unit its bound is read in (D38), for reasons and labels.

    ``relative`` is a percentage of the baseline mean (Step 2); ``absolute``
    is the metric's own unit, as points for a builtin bounded in [0, 1]
    (``points``), else the raw value (``mae``, ``rmse``, an external score).
    Float dust within ``_ZERO_TOL`` of zero (``_Drop.breached``'s tolerance)
    prints as 0, never as "1e-15 points" or "-0".
    """
    if math.isclose(value, 0.0, abs_tol=_ZERO_TOL):
        value = 0.0
    if unit is DropUnit.relative:
        return _percent(value)
    if points:
        return f"{value * 100:.4g} points"
    return f"{value:.4g}"


@dataclass(frozen=True)
class _Drop:
    metric: str
    max_drop: float
    workload_id: str
    baseline: RunStats
    trial: RunStats
    drop: float
    unit: DropUnit = DropUnit.relative
    points: bool = False

    def text(self, value: float) -> str:
        """``value`` (this drop or its bound) in this bound's unit."""
        return drop_text(value, self.unit, points=self.points)

    @property
    def breached(self) -> bool:
        """True when the drop is strictly beyond the bound."""
        return self.drop > self.max_drop and not math.isclose(
            self.drop, self.max_drop, rel_tol=1e-9, abs_tol=_ZERO_TOL
        )

    @property
    def rank(self) -> tuple[float, float]:
        """Sort key, largest worst: the share of the allowance used, then the drop.

        Drops in different units compare by that share only. A zero
        allowance has no share: breached it ranks above everything, held
        exactly it counts as fully used (1.0), improved as nothing used.
        """
        if self.max_drop > 0:
            used = self.drop / self.max_drop
        elif self.breached:
            used = math.inf
        elif math.isclose(self.drop, 0.0, abs_tol=_ZERO_TOL):
            used = 1.0
        else:
            used = -math.inf
        return used, self.drop


def _bound_fields(guardrail: Guardrail) -> tuple[str, Direction, float]:
    """Return (metric, direction, max_drop) of a metric_bound guardrail."""
    if (
        guardrail.metric is None
        or guardrail.direction is None
        or guardrail.max_drop is None
    ):
        raise ValueError(f"metric_bound guardrail {guardrail.id} is incomplete")
    return guardrail.metric, guardrail.direction, guardrail.max_drop


def _drop(expected: RunStats, actual: RunStats, guardrail: Guardrail) -> float:
    """Signed drop (negative is an improvement) in the guardrail's unit.

    ``ValueError`` for a relative drop over a zero baseline mean.
    """
    _, direction, _ = _bound_fields(guardrail)
    if guardrail.drop_unit is DropUnit.relative:
        return -relative_gain(expected, actual, direction)
    if direction is Direction.maximize:
        return expected.mean - actual.mean
    return actual.mean - expected.mean


@dataclass(frozen=True)
class GuardrailMetricJudge:
    """Every ``metric_bound`` guardrail's metric may drop at most ``max_drop``.

    The drop is signed so that a negative drop is an improvement, and read
    in the guardrail's ``drop_unit`` (D38): relative to the baseline mean
    (Step 2's rule), or absolute, in points of the metric (a quality check's
    default; defined at a zero baseline). The result's gain is minus the
    drop, in that unit; the worst is the one using most of its allowance
    (``_Drop.rank``). ``quality``, the confirmed check, only says
    whether its absolute drops print as points (a builtin bounded in [0, 1]).
    """

    quality: QualityCheck | None = None

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
            metric, _, max_drop = _bound_fields(guardrail)
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
                    drop = _drop(expected.stats, actual.stats, guardrail)
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
                        guardrail.drop_unit,
                        self._in_points(metric),
                    )
                )

        breaches = [d for d in drops if d.breached]
        if breaches:
            worst = max(breaches, key=lambda d: d.rank)
            return self._result(
                JudgeOutcome.failed,
                reason=(
                    f"{worst.metric} dropped {worst.text(worst.drop)}, more than the "
                    f"allowed {worst.text(worst.max_drop)} "
                    f"(workload {worst.workload_id})"
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
        worst = max(drops, key=lambda d: d.rank)
        return self._result(
            JudgeOutcome.passed,
            reason=(
                f"worst drop {worst.text(worst.drop)} of {worst.metric} is within the "
                f"allowed {worst.text(worst.max_drop)} (workload {worst.workload_id})"
            ),
            guardrails=len(bounds),
            worst=worst,
        )

    def _in_points(self, metric: str) -> bool:
        return (
            self.quality is not None
            and self.quality.metric == metric
            and is_point_measure(self.quality.measure)
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


# ---------------------------------------------------------------------------
# Shadow judges: they record, never decide (spec section 2)
# ---------------------------------------------------------------------------


OP_COUNT_JUDGE = "op_count"
SCALING_JUDGE = "scaling"
SHADOW_JUDGES: frozenset[str] = frozenset({OP_COUNT_JUDGE, SCALING_JUDGE})
"""Judge names whose results ``derive_verdict`` never reads (record only)."""
_SHADOW = "shadow, records only"
GROWTH_TOLERANCE = 0.15
"""Growth rates closer than this are the same growth (``ScalingJudge``):
a 5 % wobble of each size's median over the narrowest span (4x, two sizes)
moves a rate by at most about 0.07, and an algorithmic change (n^2 to
n log n or n) by 0.8 or more."""


def _split_of(row: Measurement, key: str) -> int | None:
    value = row.hardware.get(key)
    return value if type(value) is int else None


def _sum_split(rows: Sequence[Measurement], key: str) -> int | None:
    found = [_split_of(row, key) for row in rows]
    return None if None in found else sum(v for v in found if v is not None)


@dataclass(frozen=True)
class OpCountJudge:
    """Records the base's and the trial's ``op_calls`` rows (G6a).

    Summed over the workloads counted on both sides: both totals (as
    ``baseline`` and ``trial``), the Python and C split, and the relative
    change ``(trial - base) / base`` (negative: fewer calls; ``None`` over a
    zero base) in ``details``. The outcome is always ``not_applicable`` and
    ``gain`` ``None``: a second signal only, since moving work into C
    builtins can cut counted calls without cutting time, so it never
    overrides the timing judge (and ``derive_verdict`` ignores it anyway).
    """

    @property
    def name(self) -> str:
        """Judge name as it appears in results."""
        return OP_COUNT_JUDGE

    def applies_to(self, objective: Objective) -> bool:
        """It records whatever the objective is."""
        return True

    def evaluate(self, baseline: Baseline, trial: Trial) -> JudgeResult:
        """Pair the ``op_calls`` rows per workload and record the sums."""
        pairs = _pair(baseline.measurements, trial.measurements, METRIC_OP_CALLS)
        both = [(e, a) for _, e, a in pairs if a is not None]
        uncounted = len(pairs) - len(both)
        if not both:
            return JudgeResult(
                judge=self.name,
                outcome=JudgeOutcome.not_applicable,
                reason=f"{_SHADOW}: no operation counts on both sides",
                details={"shadow": True, "workloads": 0, "uncounted": uncounted},
            )
        before = [e for e, _ in both]
        after = [a for _, a in both]
        base = sum(row.stats.mean for row in before)
        total = sum(row.stats.mean for row in after)
        change = (total - base) / base if base > 0 else None
        said = "no relative change" if change is None else f"{change:+.1%}"
        missing = f"; {uncounted} not counted on both sides" if uncounted else ""
        return JudgeResult(
            judge=self.name,
            outcome=JudgeOutcome.not_applicable,
            metric=METRIC_OP_CALLS,
            baseline=RunStats.from_samples((base,), unit="calls"),
            trial=RunStats.from_samples((total,), unit="calls"),
            reason=(
                f"{_SHADOW}: {total:.0f} calls against the base's {base:.0f}"
                f" ({said}) over {len(both)} workload(s){missing}"
            ),
            details={
                "shadow": True,
                "workloads": len(both),
                "uncounted": uncounted,
                "change": change,
                "base_calls": round(base),
                "trial_calls": round(total),
                "base_python_calls": _sum_split(before, PYTHON_CALLS_KEY),
                "base_c_calls": _sum_split(before, C_CALLS_KEY),
                "trial_python_calls": _sum_split(after, PYTHON_CALLS_KEY),
                "trial_c_calls": _sum_split(after, C_CALLS_KEY),
            },
        )


def growth_rate(points: Sequence[tuple[int, float]]) -> float:
    """The least-squares slope of log(time) against log(size) over
    ``points`` (two or more distinct positive sizes, positive times): 1 for
    time growing linearly with size, 2 quadratically."""
    xs = [math.log(size) for size, _ in points]
    ys = [math.log(seconds) for _, seconds in points]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    spread = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / spread


def _tidy(value: float) -> float:
    """Rounded to 6 places (float noise is no growth), never ``-0.0``."""
    return round(value, 6) + 0.0


def _medians(rows: Sequence[Measurement]) -> dict[str, dict[int, float]]:
    """Per workload, each size's median scaling time: the first row per
    (workload, size), only a positive int size and a positive median."""
    found: dict[str, dict[int, float]] = {}
    for row in rows:
        size = row.hardware.get(SCALE_SIZE_KEY)
        if row.metric != METRIC_SCALE_WALL_S or type(size) is not int or size < 1:
            continue
        sizes = found.setdefault(row.workload_id, {})
        if size not in sizes and (median := statistics.median(row.samples)) > 0:
            sizes[size] = median
    return found


@dataclass(frozen=True)
class ScalingJudge:
    """Records how run time grows with input size on both sides (G6b).

    Per workload scaled on both sides (``scale_wall_time_s`` rows), the
    growth rate of each side (``growth_rate`` over the medians of the sizes
    both ran, two at least); recorded: the mean rates (``baseline`` and
    ``trial`` hold the per-workload rates, unit ``rate``), their difference
    ``change`` (negative: slower growth), the ``largest_change`` of one
    workload, and ``same_growth`` (every change within
    ``GROWTH_TOLERANCE``). A real algorithmic change alters the rate, a
    constant-factor speed-up does not. The outcome is always
    ``not_applicable`` and ``gain`` ``None`` (``derive_verdict`` ignores it
    anyway).
    """

    @property
    def name(self) -> str:
        """Judge name as it appears in results."""
        return SCALING_JUDGE

    def applies_to(self, objective: Objective) -> bool:
        """It records whatever the objective is."""
        return True

    def evaluate(self, baseline: Baseline, trial: Trial) -> JudgeResult:
        """Fit both sides' growth per workload and record the rates."""
        after = _medians(trial.measurements)
        rates: list[tuple[float, float]] = []
        before = _medians(baseline.measurements)
        for workload_id, base in before.items():
            mine = after.get(workload_id, {})
            shared = sorted(set(base) & set(mine))
            if len(shared) >= 2:
                rates.append((
                    growth_rate([(size, base[size]) for size in shared]),
                    growth_rate([(size, mine[size]) for size in shared]),
                ))  # fmt: skip
        unscaled = len(before) - len(rates)
        if not rates:
            return JudgeResult(
                judge=self.name,
                outcome=JudgeOutcome.not_applicable,
                reason=f"{_SHADOW}: no scaling runs on both sides",
                details={"shadow": True, "workloads": 0, "unscaled": unscaled},
            )
        changes = [_tidy(t - b) for b, t in rates]
        base_rate = _tidy(statistics.fmean(b for b, _ in rates))
        trial_rate = _tidy(statistics.fmean(t for _, t in rates))
        change = _tidy(trial_rate - base_rate)
        missing = f"; {unscaled} not scaled on both sides" if unscaled else ""
        return JudgeResult(
            judge=self.name,
            outcome=JudgeOutcome.not_applicable,
            metric=METRIC_SCALE_WALL_S,
            baseline=RunStats.from_samples([b for b, _ in rates], unit="rate"),
            trial=RunStats.from_samples([t for _, t in rates], unit="rate"),
            reason=(
                f"{_SHADOW}: growth rate {trial_rate:.2f} against the base's"
                f" {base_rate:.2f} ({change:+.2f}) over {len(rates)} workload(s){missing}"
            ),
            details={
                "shadow": True,
                "workloads": len(rates),
                "unscaled": unscaled,
                "base_rate": base_rate,
                "trial_rate": trial_rate,
                "change": change,
                "largest_change": max(changes, key=abs),
                "tolerance": GROWTH_TOLERANCE,
                "same_growth": all(abs(c) <= GROWTH_TOLERANCE for c in changes),
            },
        )


def default_judges(
    noise_multiplier: float = 2.0,
    *,
    quality: QualityCheck | None = None,
    op_count: bool = False,
    scaling: bool = False,
) -> tuple[Judge, ...]:
    """The frozen judge set in evaluation order (``quality``: the confirmed
    check; ``op_count`` and ``scaling``: the shadow :class:`OpCountJudge`
    and :class:`ScalingJudge` last, in that order).

    Keep ``EquivalenceJudge`` in any judge set: it is the only judge that sets
    ``output_changed``, which rule 6 of :func:`derive_verdict` relies on to
    send a changed output to review instead of keeping it.
    """
    judges: tuple[Judge, ...] = (
        SpeedJudge(noise_multiplier=noise_multiplier),
        MemoryJudge(noise_multiplier=noise_multiplier),
        EquivalenceJudge(),
        GuardrailMetricJudge(quality=quality),
        TestSuiteJudge(),
    )
    shadow = (OpCountJudge(),) * op_count + (ScalingJudge(),) * scaling
    return (*judges, *shadow)


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

    0. a quarantined proposal (G3, ``anticheat.proposal_conflict``) ->
       reject, whatever the judges say: its tag and a claim of equivalent
       output are contradictory, so no tagged trial is ever kept or reviewed;
    1. any violation -> reject;
    2. trial failed or rejected -> reject;
    3. any judge failed -> reject;
    4. the primary objective judge or any guardrail judge inconclusive ->
       inconclusive (a secondary objective inside its noise floor is neutral);
    5. no objective judge (one carrying a metric) passed -> inconclusive;
    6. all passed (D35): any result with ``output_changed`` -> review, never
       keep (novel stays needs_approval); otherwise efficiency -> keep,
       behaviour -> review (D10, user decision 1: its own branch, no pause)
       and novel -> needs_approval.

    Rule 6 relies on :class:`EquivalenceJudge` being among the judges that
    produced ``judge_results``: it is the only judge that sets
    ``output_changed``, so without it a changed output is never seen here.

    Results of ``SHADOW_JUDGES`` take part in no rule and in no gain,
    whatever they say: they are kept on the verdict, in order, and nothing
    more.
    """
    results = tuple(judge_results)
    deciding = tuple(r for r in results if r.judge not in SHADOW_JUDGES)
    found = tuple(violations)
    change_class = hypothesis.change_class
    quarantined = proposal_conflict(hypothesis, deciding)
    if quarantined is not None:  # rule 0 (G3): before every other rule
        outcome, summary = VerdictOutcome.reject, f"reject: {quarantined}"
    else:
        outcome, summary = _decide(trial, change_class, deciding, found, primary_metric)
    return Verdict(
        trial_id=trial.id,
        hypothesis_id=hypothesis.id,
        outcome=outcome,
        change_class=change_class,
        judge_results=results,
        violations=found,
        gain=_select_gain(deciding, primary_metric),
        summary=summary,
    )


def _blocks_when_inconclusive(result: JudgeResult, primary: str | None) -> bool:
    """Guardrail judges and the primary objective must be conclusive.

    A secondary objective that sits inside its own noise floor is neutral:
    it neither proves nor disproves anything, and must not veto a primary
    gain. Regressions beyond noise still fail (rule 3).
    """
    return result.metric is None or primary is None or result.metric == primary


def _decide(
    trial: Trial,
    change_class: ChangeClass,
    results: tuple[JudgeResult, ...],
    violations: tuple[Violation, ...],
    primary: str | None,
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
    inconclusive = next(
        (
            r
            for r in results
            if r.outcome is JudgeOutcome.inconclusive
            and _blocks_when_inconclusive(r, primary)
        ),
        None,
    )
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
    return _rule_6(change_class, results)


def _rule_6(
    change_class: ChangeClass, results: tuple[JudgeResult, ...]
) -> tuple[VerdictOutcome, str]:
    """Rule 6, once rules 1-5 have let every result through."""
    changed = any(r.output_changed is True for r in results)
    if change_class is ChangeClass.novel:
        note = "; output changed" if changed else ""
        return (
            VerdictOutcome.needs_approval,
            f"needs_approval: all judges passed{note}; "
            f"{change_class} change needs human approval",
        )
    if changed:
        return (
            VerdictOutcome.review,
            f"review: all judges passed; output changed within the quality "
            f"check; {change_class} change goes to the review branch",
        )
    if change_class is ChangeClass.efficiency:
        return (
            VerdictOutcome.keep,
            "keep: all judges passed; efficiency change ships automatically",
        )
    return (
        VerdictOutcome.review,
        f"review: all judges passed; {change_class} change goes to the review branch",
    )
