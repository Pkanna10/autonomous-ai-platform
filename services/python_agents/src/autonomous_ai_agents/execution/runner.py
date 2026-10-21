"""Trial runner: the seam between the orchestrator and the user's hardware.

``TrialRunner`` is what the trials node calls for every hypothesis. The real
runner (Step 2) creates a git worktree, lets Claude edit the code, runs each
workload N times and measures it. ``StubTrialRunner`` replays scripted
outcomes instead, so the whole loop is testable with no subprocess, git or
LLM involved and the judges see exactly the measurements the test scripted.
"""

from __future__ import annotations

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


@runtime_checkable
class TrialRunner(Protocol):
    """Runs one hypothesis against the workloads and reports a measured Trial."""

    def run(
        self,
        hypothesis: Hypothesis,
        workloads: Sequence[Workload],
        baseline: Baseline,
        *,
        round: int,
        branch: str,
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
    call is appended to ``calls`` as ``(hypothesis id, round)`` so tests can
    assert what the trials node asked for. Output is deterministic apart from
    the fresh trial and measurement ids and the timestamps.
    """

    def __init__(
        self,
        scripts: Mapping[str, ScriptedOutcome],
        default: ScriptedOutcome | None = None,
    ) -> None:
        self._scripts: dict[str, ScriptedOutcome] = dict(scripts)
        self._default = default
        self.calls: list[tuple[str, int]] = []

    def run(
        self,
        hypothesis: Hypothesis,
        workloads: Sequence[Workload],
        baseline: Baseline,
        *,
        round: int,
        branch: str,
    ) -> Trial:
        """Return the scripted Trial for ``hypothesis`` (see class docstring)."""
        self.calls.append((hypothesis.id, round))
        script = self._script_for(hypothesis)
        trial_id = new_id()
        started_at = utc_now()
        measurements = (
            ()
            if script.error is not None
            else _measurements(trial_id, workloads, script)
        )
        return Trial(
            id=trial_id,
            hypothesis_id=hypothesis.id,
            round=round,
            branch=branch,
            touched_paths=tuple(script.touched_paths),
            status=TrialStatus.failed if script.error else TrialStatus.measured,
            measurements=measurements,
            error=script.error,
            started_at=started_at,
            finished_at=utc_now(),
            tokens_used=script.tokens_used,
            cost_usd=script.cost_usd,
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
    trial_id: str, workloads: Sequence[Workload], script: ScriptedOutcome
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
