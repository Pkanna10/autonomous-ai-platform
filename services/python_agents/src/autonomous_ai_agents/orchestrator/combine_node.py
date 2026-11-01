"""The combine step: merge the kept changes, re-judge the tip, fall back once.

The combine node (``nodes.py``) delegates here when a ``Combiner`` is wired:

1. ``kept_changes`` turns the kept verdicts (after approval) into
   ``KeptChange``s, ordered by hypothesis score descending, then id.
2. ``combine_kept`` calls the combiner, then judges what it measured with the
   frozen judges: the interleaved A runs become a ``Baseline`` (objectives and
   guardrails copied from the run's baseline), the B runs a transient
   ``Trial`` of a synthetic efficiency ``Hypothesis``, and the completeness
   rule runs on both sides. The combination holds iff ``derive_verdict``
   returns an outcome in ``CombineRules.accept`` (``keep``; the review set
   also takes ``review``, D10) and something was applied.
3. When it does not hold, the single best kept change (highest gain, then
   hypothesis id) is re-tested once, never the set that just failed.
4. The applied changes' verdict ids are kept only if a re-test held; the
   ``Combination`` records the greedy result, any fallback and the outcome.

``retest_one`` is the same re-test on one change, with no fallback: the
confirmation's second look (``confirm.py``, D41 b).

Nothing here is stored: neither the transient trial nor the synthetic
hypothesis reaches the repository, and lessons stay as the verdicts made them.
Every function is pure apart from the one or two ``Combiner.combine`` calls.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from autonomous_ai_agents.common.errors import EngineError
from autonomous_ai_agents.common.models import (
    Baseline,
    ChangeClass,
    Combination,
    CombineSkip,
    FrozenFile,
    Guardrail,
    Hypothesis,
    HypothesisSource,
    Measurement,
    Objective,
    Project,
    Trial,
    TrialStatus,
    Verdict,
    VerdictOutcome,
    Violation,
    Workload,
)
from autonomous_ai_agents.execution.protocols import (
    CombineMeasured,
    Combiner,
    KeptChange,
)
from autonomous_ai_agents.optimization.judges import Judge, derive_verdict

COMBINATION_ID = "combination"
"""Hypothesis id of the transient trial that stands for the combined tip."""

_COMMIT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


def is_commit(value: str) -> bool:
    """True for a full lowercase SHA-1 or SHA-256 commit id (never an option)."""
    return _COMMIT.fullmatch(value) is not None


@dataclass(frozen=True)
class CombineRules:
    """How a re-test is judged: the run's frozen judges and its baseline rules.

    ``completeness`` is the verdicts node's rule (every objective and
    guardrail metric measured exactly once per workload, objectives over
    enough runs), applied to the B runs and the A runs alike.
    ``baseline_count`` is the baseline suite's passing-test count: the tip's
    suite must reach it, as every trial's must. ``accept`` holds the
    outcomes a re-test may end in and still hold: ``keep`` alone for the run
    branch, ``keep`` or ``review`` for the review set (D10).
    """

    judges: tuple[Judge, ...]
    objectives: tuple[Objective, ...]
    guardrails: tuple[Guardrail, ...]
    primary: str | None
    completeness: Callable[[Sequence[Measurement]], tuple[Violation, ...]]
    baseline_count: int | None = None
    accept: frozenset[VerdictOutcome] = frozenset({VerdictOutcome.keep})


@dataclass(frozen=True)
class CombineTarget:
    """Where the combiner works: the run, the project, the base and the branch;
    ``quality_files`` are the baseline's frozen files the re-test scores
    against (``Baseline.quality_files``, D37)."""

    run_id: str
    project: Project
    base_commit: str
    workloads: tuple[Workload, ...]
    branch: str
    round: int
    quality_files: tuple[FrozenFile, ...] = ()


@dataclass(frozen=True)
class CombineOutcome:
    """What the combine node writes: the verdict ids to deliver and the record."""

    kept_verdict_ids: tuple[str, ...]
    combination: Combination


@dataclass(frozen=True)
class Retest:
    """One re-test: what the combiner measured, its verdict, and whether it
    holds (something applied, the outcome in ``accept``)."""

    measured: CombineMeasured
    verdict: Verdict
    accept: frozenset[VerdictOutcome]

    @property
    def holds(self) -> bool:
        return bool(self.measured.applied) and self.verdict.outcome in self.accept

    @property
    def reason(self) -> str:
        """Why it held or not (:func:`_why`)."""
        return _why(self)


def kept_changes(
    kept: Sequence[Verdict],
    trials: Mapping[str, Trial],
    hypotheses: Mapping[str, Hypothesis],
) -> list[KeptChange]:
    """The kept verdicts as committed changes, by score descending, then id.

    Raises ``EngineError`` for a verdict whose trial is unknown or was never
    committed: there is nothing to merge. A hypothesis missing from the state
    scores 0.
    """
    changes: list[KeptChange] = []
    for verdict in kept:
        trial = trials.get(verdict.trial_id)
        if trial is None or trial.commit is None:
            raise EngineError(
                f"kept verdict {verdict.id} has no committed trial to combine"
            )
        hypothesis = hypotheses.get(verdict.hypothesis_id)
        changes.append(
            KeptChange(
                trial_id=trial.id,
                hypothesis_id=verdict.hypothesis_id,
                verdict_id=verdict.id,
                commit=trial.commit,
                score=0.0 if hypothesis is None else hypothesis.score,
                gain=verdict.gain,
            )
        )
    return sorted(changes, key=lambda change: (-change.score, change.hypothesis_id))


def combine_kept(
    combiner: Combiner,
    changes: Sequence[KeptChange],
    rules: CombineRules,
    target: CombineTarget,
) -> CombineOutcome:
    """Combine ``changes`` greedily, re-judge, fall back once (module docstring)."""
    greedy = _retest(combiner, changes, rules, target)
    fallback: KeptChange | None = None
    final = greedy
    if not greedy.holds:
        fallback = _fallback_candidate(changes, greedy.measured.applied)
        if fallback is not None:
            final = _retest(combiner, (fallback,), rules, target)
    verdict_for = {change.trial_id: change.verdict_id for change in changes}
    kept_ids = (
        tuple(verdict_for[trial_id] for trial_id in final.measured.applied)
        if final.holds
        else ()
    )
    skipped = (
        greedy.measured.skipped
        if final is greedy
        else (*greedy.measured.skipped, *final.measured.skipped)
    )
    return CombineOutcome(
        kept_verdict_ids=kept_ids,
        combination=Combination(
            base_commit=target.base_commit,
            tip_commit=final.measured.tip_commit,
            applied_trial_ids=final.measured.applied,
            skipped=skipped,
            judge_results=final.verdict.judge_results,
            holds=final.holds,
            fallback_trial_id=None if fallback is None else fallback.trial_id,
            summary=_summary(changes, greedy, fallback, final, kept_ids),
        ),
    )


def retest_one(
    combiner: Combiner, change: KeptChange, rules: CombineRules, target: CombineTarget
) -> Retest:
    """Re-test ``change`` alone, ABAB from the base, judged as combine judges."""
    return _retest(combiner, (change,), rules, target)


def _retest(
    combiner: Combiner,
    offered: Sequence[KeptChange],
    rules: CombineRules,
    target: CombineTarget,
) -> Retest:
    args = (target.run_id, target.project, target.base_commit, offered)
    # Step 2 combiners need not know the keyword: pass it only with files.
    measured = (
        combiner.combine(
            *args,
            target.workloads,
            baseline_count=rules.baseline_count,
            quality_files=target.quality_files,
        )
        if target.quality_files
        else combiner.combine(
            *args, target.workloads, baseline_count=rules.baseline_count
        )
    )
    _check_measured(measured, offered)
    baseline = Baseline(
        commit=target.base_commit,
        measurements=measured.baseline,
        objectives=rules.objectives,
        guardrails=rules.guardrails,
    )
    trial = Trial(
        hypothesis_id=COMBINATION_ID,
        round=target.round,
        branch=target.branch,
        base_commit=target.base_commit,
        commit=measured.tip_commit,
        status=TrialStatus.measured,
        measurements=measured.combined,
    )
    results = tuple(judge.evaluate(baseline, trial) for judge in rules.judges)
    found = (
        *rules.completeness(measured.combined),
        *(
            violation.model_copy(
                update={"message": f"interleaved baseline: {violation.message}"}
            )
            for violation in rules.completeness(measured.baseline)
        ),
    )
    hypothesis = Hypothesis(
        id=COMBINATION_ID,
        project_id=target.project.id,
        source=HypothesisSource.playbook,
        title="combination of the kept changes",
        rationale="each change was kept or approved on its own",
        change_class=ChangeClass.efficiency,
        expected_gain=0.0,
        provability=1.0,
        risk=0.0,
    )
    verdict = derive_verdict(
        trial, hypothesis, results, found, primary_metric=rules.primary
    )
    return Retest(measured, verdict, rules.accept)


def _check_measured(measured: CombineMeasured, offered: Sequence[KeptChange]) -> None:
    """Refuse a combiner result naming trials it was not given, or a bad tip."""
    named = [*measured.applied, *(skip.trial_id for skip in measured.skipped)]
    unknown = sorted(set(named) - {change.trial_id for change in offered})
    if unknown:
        raise EngineError(
            "combiner reported trial(s) it was not given: " + ", ".join(unknown)
        )
    if len(set(named)) != len(named):
        raise EngineError("combiner reported a trial more than once")
    if not is_commit(measured.tip_commit):
        raise EngineError(
            f"combiner returned {measured.tip_commit!r}, which is not a commit id"
        )


def _fallback_candidate(
    changes: Sequence[KeptChange], failed: Sequence[str]
) -> KeptChange | None:
    """The best single change by gain then hypothesis id, never the failed set."""
    candidates = [c for c in changes if (c.trial_id,) != tuple(failed)]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda c: (-(c.gain if c.gain is not None else -math.inf), c.hypothesis_id),
    )


def _why(retest: Retest) -> str:
    """Why a re-test held or not: its verdict, or that nothing was applied.

    An empty application never holds, whatever the B runs say (the tip is
    the base), so the verdict would be the wrong reason to give. Otherwise
    the verdict summary, plus the first violation's message (rules alone are
    terse). Applied changes with no rows on either side mean the combiner
    caught a run failure: a crash, not an anti-cheating violation.
    """
    verdict, measured = retest.verdict, retest.measured
    if not measured.applied:
        return "nothing was applied (tip is the base)"
    if not measured.baseline and not measured.combined:
        return (
            "the re-test produced no measurements (a workload or the suite "
            "failed on the second look)"
        )
    if not verdict.violations:
        return verdict.summary
    return f"{verdict.summary} ({verdict.violations[0].message})"


def _skip_text(skip: CombineSkip) -> str:
    where = f" in {', '.join(skip.paths)}" if skip.paths else ""
    return f"trial {skip.trial_id[:8]} ({skip.reason}{where})"


def _summary(
    changes: Sequence[KeptChange],
    greedy: Retest,
    fallback: KeptChange | None,
    final: Retest,
    kept_ids: Sequence[str],
) -> str:
    applied = len(greedy.measured.applied)
    parts = [
        f"greedy merge applied {applied} of {len(changes)} kept change(s)"
        if applied
        else f"greedy merge applied nothing of {len(changes)} kept change(s)"
    ]
    if greedy.measured.skipped:
        parts.append(
            f"skipped {len(greedy.measured.skipped)}: "
            + ", ".join(_skip_text(skip) for skip in greedy.measured.skipped)
        )
    parts.append(
        f"re-test {'held' if greedy.holds else 'did not hold'}: {_why(greedy)}"
    )
    if not greedy.holds:
        if fallback is None:
            parts.append("no fallback: no other single change to re-test")
        else:
            parts.append(
                f"fallback re-tested trial {fallback.trial_id[:8]} alone and "
                f"{'held' if final.holds else 'did not hold'}: {_why(final)}"
            )
    parts.append(
        f"outcome: {len(kept_ids)} change(s) delivered"
        if kept_ids
        else "outcome: nothing delivered, report only"
    )
    return "; ".join(parts)
