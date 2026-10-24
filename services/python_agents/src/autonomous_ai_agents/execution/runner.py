"""Trial runner: the seam between the orchestrator and the user's hardware.

``TrialRunner`` is what the trials node calls for every hypothesis. The real
runner (Step 2) creates a git worktree, lets Claude edit the code, runs each
workload N times and measures it. ``StubTrialRunner`` replays scripted
outcomes instead, so the whole loop is testable with no subprocess, git or
LLM involved and the judges see exactly the measurements the test scripted.

``BaselineRunner`` is the same seam for the baseline node: it measures the
untouched code once per workload (``trial_id`` is ``None``). The real one
shares the runner's measurement code in Step 2; ``StubBaselineRunner`` replays
one ``ScriptedOutcome`` for every workload.

Step 2 passes every trial the money it may still spend (``budget_usd``) and
its ``TrialBrief``, and every baseline the run id (which names its worktree)
and the pinned commit. The real runners raise ``ValueError`` when ``commit``
is ``None``; the stubs accept and record what they are given.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from autonomous_ai_agents.common.models import (
    METRIC_TESTS_PASSED,
    Baseline,
    Hypothesis,
    Measurement,
    RunStats,
    Trial,
    TrialStatus,
    Workload,
    new_id,
    utc_now,
)
from autonomous_ai_agents.execution.protocols import TrialBrief

OVER_BUDGET_ERROR = "scripted cost exceeds budget"
"""The stub's error for a trial scripted to cost more than its ``budget_usd``."""


@runtime_checkable
class TrialRunner(Protocol):
    """Runs one hypothesis against the workloads and reports a measured Trial.

    ``budget_usd`` is the most the trial may spend; a runner never reports a
    ``cost_usd`` above it. ``brief`` is what the trial's editor is told.
    """

    def run(
        self,
        hypothesis: Hypothesis,
        workloads: Sequence[Workload],
        baseline: Baseline,
        *,
        round: int,
        branch: str,
        budget_usd: float,
        brief: TrialBrief,
    ) -> Trial: ...


@dataclass(frozen=True)
class ScriptedOutcome:
    """What the stub runner reports for one hypothesis.

    ``samples`` maps a metric name to the raw per-run samples every workload
    will report. ``error`` turns the trial into a failed one with no
    measurements. ``tests_passed`` adds a ``tests_passed`` measurement per
    workload when set.
    """

    touched_paths: tuple[str, ...] = ()
    samples: Mapping[str, tuple[float, ...]] = field(default_factory=dict)
    output_fingerprint: str | None = None
    tests_passed: bool | None = None
    error: str | None = None
    cost_usd: float = 0.0
    tokens_used: int = 0


def _unit_for(metric: str) -> str:
    if metric.endswith("_s"):
        return "s"
    if metric.endswith("_bytes"):
        return "bytes"
    return ""


class StubTrialRunner:
    """A ``TrialRunner`` that replays ``ScriptedOutcome``s.

    Scripts are looked up by hypothesis id, then by hypothesis title, then
    ``default``; with none of them a ``KeyError`` names the hypothesis. Every
    call is appended to ``calls`` as ``(hypothesis id, round)``, and its
    ``budget_usd`` and ``brief`` to ``budgets`` and ``briefs``, so tests can
    assert what the trials node asked for. A script costing more than
    ``budget_usd`` gives a failed trial (``OVER_BUDGET_ERROR``) with no
    touched paths: a real editor stops at its budget check, before capture,
    so no runner reports more. Any trial whose cost is capped this way is
    charged the whole budget and the same share of its scripted tokens
    (rounded down). Output is deterministic apart from the fresh trial and
    measurement ids and the timestamps.
    """

    def __init__(
        self,
        scripts: Mapping[str, ScriptedOutcome],
        default: ScriptedOutcome | None = None,
    ) -> None:
        self._scripts: dict[str, ScriptedOutcome] = dict(scripts)
        self._default = default
        self.calls: list[tuple[str, int]] = []
        self.budgets: list[float] = []
        self.briefs: list[TrialBrief] = []

    def run(
        self,
        hypothesis: Hypothesis,
        workloads: Sequence[Workload],
        baseline: Baseline,
        *,
        round: int,
        branch: str,
        budget_usd: float,
        brief: TrialBrief,
    ) -> Trial:
        """Return the scripted Trial for ``hypothesis`` (see class docstring)."""
        if not math.isfinite(budget_usd) or budget_usd < 0:
            raise ValueError(
                f"budget_usd must be finite and at least 0, got {budget_usd}"
            )
        self.calls.append((hypothesis.id, round))
        self.budgets.append(budget_usd)
        self.briefs.append(brief)
        script = self._script_for(hypothesis)
        over_budget = script.error is None and script.cost_usd > budget_usd
        error = OVER_BUDGET_ERROR if over_budget else script.error
        cost_usd = min(script.cost_usd, budget_usd)
        tokens_used = script.tokens_used
        if cost_usd < script.cost_usd:  # capped: the same share of the tokens
            tokens_used = math.floor(script.tokens_used * cost_usd / script.cost_usd)
        trial_id = new_id()
        started_at = utc_now()
        measurements = (
            () if error is not None else _measurements(trial_id, workloads, script)
        )
        return Trial(
            id=trial_id,
            hypothesis_id=hypothesis.id,
            round=round,
            branch=branch,
            touched_paths=() if over_budget else tuple(script.touched_paths),
            status=TrialStatus.failed if error else TrialStatus.measured,
            measurements=measurements,
            error=error,
            started_at=started_at,
            finished_at=utc_now(),
            tokens_used=tokens_used,
            cost_usd=cost_usd,
        )

    def _script_for(self, hypothesis: Hypothesis) -> ScriptedOutcome:
        for key in (hypothesis.id, hypothesis.title):
            script = self._scripts.get(key)
            if script is not None:
                return script
        if self._default is not None:
            return self._default
        raise KeyError(
            f"no scripted outcome for hypothesis {hypothesis.id!r} "
            f"(title {hypothesis.title!r}): script it by id or title, "
            "or give StubTrialRunner a default"
        )


def _measurements(
    trial_id: str | None, workloads: Sequence[Workload], script: ScriptedOutcome
) -> tuple[Measurement, ...]:
    measurements: list[Measurement] = []
    for workload in workloads:
        for metric, raw in script.samples.items():
            samples = tuple(float(value) for value in raw)
            measurements.append(
                Measurement(
                    workload_id=workload.id,
                    trial_id=trial_id,
                    metric=metric,
                    stats=RunStats.from_samples(samples, unit=_unit_for(metric)),
                    samples=samples,
                    output_fingerprint=script.output_fingerprint,
                )
            )
        if script.tests_passed is not None:
            flag = (1.0,) if script.tests_passed else (0.0,)
            measurements.append(
                Measurement(
                    workload_id=workload.id,
                    trial_id=trial_id,
                    metric=METRIC_TESTS_PASSED,
                    stats=RunStats.from_samples(flag, unit="bool"),
                    samples=flag,
                )
            )
    return tuple(measurements)


@runtime_checkable
class BaselineRunner(Protocol):
    """Measures the untouched code on every workload (``trial_id`` is ``None``).

    ``run_id`` names the baseline's own worktree; ``commit`` is the pinned
    base commit the real runner checks out (it refuses ``None``).
    """

    def measure(
        self, workloads: Sequence[Workload], *, run_id: str, commit: str | None
    ) -> tuple[Measurement, ...]: ...


class StubBaselineRunner:
    """A ``BaselineRunner`` that replays one ``ScriptedOutcome`` per workload.

    Measurements are built exactly as ``StubTrialRunner`` builds them for a
    trial (one per workload and metric, plus ``tests_passed`` when scripted)
    but with no trial id. The script's ``touched_paths``, ``error``, cost and
    token fields are ignored: a baseline has no diff and costs no tokens.
    ``run_id`` and ``commit`` are accepted and ignored (both default to
    ``None``). Every call is appended to ``calls`` as ``(workload ids,
    run_id, commit)``.
    """

    def __init__(self, script: ScriptedOutcome) -> None:
        self._script = script
        self.calls: list[tuple[tuple[str, ...], str | None, str | None]] = []

    def measure(
        self,
        workloads: Sequence[Workload],
        *,
        run_id: str | None = None,
        commit: str | None = None,
    ) -> tuple[Measurement, ...]:
        """Return the scripted baseline measurements for ``workloads``."""
        self.calls.append((tuple(w.id for w in workloads), run_id, commit))
        return _measurements(None, workloads, self._script)
