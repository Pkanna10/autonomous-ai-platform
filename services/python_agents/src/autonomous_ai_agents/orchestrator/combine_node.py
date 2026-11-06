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
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, replace
from typing import Final, Protocol, runtime_checkable

from autonomous_ai_agents.common.config import SiteStacks
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
    KeepRecord,
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
from autonomous_ai_agents.execution.combine import DryMerge
from autonomous_ai_agents.execution.protocols import (
    CombineMeasured,
    Combiner,
    KeptChange,
)
from autonomous_ai_agents.optimization.evolve import (
    hunk_signature,
    reconcile_eligibility,
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


EXACT_MAX: Final = 9
"""S2: a conflict component of at most this many nodes gets its exact max-sum
subset (at most 2^9 subsets); a larger one the greedy subset by gain."""


@runtime_checkable
class ConflictProbe(Protocol):
    """A combiner that can dry-merge (S2): ``GitCombiner``."""

    site_stacks: SiteStacks

    def dry_merge(
        self, project: Project, base_commit: str, kept: Sequence[KeptChange]
    ) -> DryMerge: ...


def order_gain(verdict: Verdict) -> float | None:
    """S2's order key: the mean of both looks (D42's ``reported_gain``), the
    first look when the confirmation was skipped."""
    first, second = verdict.gain, verdict.confirmed_gain
    return first if first is None or second is None else (first + second) / 2


@dataclass(frozen=True)
class DeliveryPlan:
    """What S2 offers the greedy merge (``order``) and what it records: each
    keep's order gain, its component and duplicate, the best subsets, the
    dry merge's conflicting pairs (trial ids throughout)."""

    order: tuple[KeptChange, ...]
    gains: Mapping[str, float | None]
    conflicts: frozenset[frozenset[str]]
    duplicate_of: Mapping[str, str]
    component: Mapping[str, int]
    best: frozenset[str]


def plan_delivery(
    changes: Sequence[KeptChange],
    gains: Mapping[str, float | None],
    dry: DryMerge,
    *,
    by_gain: bool,
) -> DeliveryPlan:
    """The plan for ``changes`` (score order): hunk-identical keeps are one
    node, its highest gain the representative; components of the conflict
    graph by gain; each component's max-sum conflict-free subset. ``by_gain``
    (``on``) offers the subsets first, then the other nodes, then the
    duplicates, each by gain; else ``changes`` as given (``record``)."""

    def gain(c: KeptChange) -> float:
        value = gains.get(c.trial_id)
        return -math.inf if value is None else value

    ranked = sorted(changes, key=lambda c: (-gain(c), -c.score, c.hypothesis_id))
    first: dict[str, str] = {}  # a hunk signature's highest-gain keep
    rep = {}
    for c in ranked:
        sig = hunk_signature(dry.diffs.get(c.trial_id, ""))
        rep[c.trial_id] = (
            c.trial_id if sig is None else first.setdefault(sig, c.trial_id)
        )
    nodes = [c for c in ranked if rep[c.trial_id] == c.trial_id]
    edges = {
        frozenset(rep[t] for t in pair) for pair in dry.conflicts if pair <= rep.keys()
    }
    edges = {e for e in edges if len(e) == 2}
    component: dict[str, int] = {}
    for c in nodes:  # components in gain order, a breadth-first walk each
        if c.trial_id not in component:
            todo, n = [c.trial_id], len(set(component.values()))
            while todo:
                here = todo.pop()
                component[here] = n
                todo += [o for o in (t for e in edges if here in e for t in e) if o not in component]  # fmt: skip
    best: set[str] = set()
    for n in set(component.values()):
        members = [c for c in nodes if component[c.trial_id] == n]
        best |= _best_subset(members, edges, gain)
    duplicate_of = {c.trial_id: rep[c.trial_id] for c in ranked if rep[c.trial_id] != c.trial_id}  # fmt: skip
    for dup, stands in duplicate_of.items():
        component[dup] = component[stands]
    order = tuple(changes) if not by_gain else (
        *(c for c in nodes if c.trial_id in best),
        *(c for c in nodes if c.trial_id not in best),
        *(c for c in ranked if c.trial_id in duplicate_of),
    )  # fmt: skip
    return DeliveryPlan(order, {c.trial_id: gains.get(c.trial_id) for c in changes},
                        frozenset(dry.conflicts), duplicate_of, component, frozenset(best))  # fmt: skip


def _best_subset(
    members: Sequence[KeptChange],
    edges: AbstractSet[frozenset[str]],
    gain: Callable[[KeptChange], float],
) -> set[str]:
    """The conflict-free subset of ``members`` (in gain order) with the
    largest summed gain (a negative or missing gain weighs 0), the larger
    and earlier one on a tie; greedy by gain above ``EXACT_MAX``."""
    ids = [c.trial_id for c in members]
    weight = [max(gain(c), 0.0) for c in members]
    clash = [sum(1 << j for j, o in enumerate(ids) if frozenset({t, o}) in edges)
             for t in ids]  # fmt: skip
    if len(ids) > EXACT_MAX:
        taken = 0
        for i in range(len(ids)):
            taken |= (1 << i) if not clash[i] & taken else 0
        return {t for i, t in enumerate(ids) if taken >> i & 1}
    top, pick = (-1.0, -1), 0
    for mask in range(1 << len(ids)):
        on = [i for i in range(len(ids)) if mask >> i & 1]
        if all(not clash[i] & mask for i in on):
            key = (round(math.fsum(weight[i] for i in on), 12), len(on))
            top, pick = (key, mask) if key > top else (top, pick)
    return {t for i, t in enumerate(ids) if pick >> i & 1}


def keep_records(
    plan: DeliveryPlan, outcome: CombineOutcome, trials: Mapping[str, Trial]
) -> CombineOutcome:
    """``outcome`` with one ``KeepRecord`` per offered keep (in offered order)
    and the conflicting pairs: delivered or the first skip's reason, else why
    the combination lost it; the blocker, the duplicate, part 3's record for
    a blocked keep that is not a duplicate (trials none)."""
    combination = outcome.combination
    skips: dict[str, CombineSkip] = {}
    for one in combination.skipped:
        skips.setdefault(one.trial_id, one)
    delivered = set(outcome.kept_verdict_ids)
    fallback = combination.fallback_trial_id
    records = []
    for c in plan.order:
        skip = skips.get(c.trial_id)
        why = None if c.verdict_id in delivered else _lost(c.trial_id, skip, fallback)
        blocker = None if skip is None else skip.blocked_by
        records.append(KeepRecord(
            trial_id=c.trial_id, verdict_id=c.verdict_id, gain=plan.gains.get(c.trial_id),
            component=plan.component[c.trial_id], best_subset=c.trial_id in plan.best,
            delivered=why is None, skip_reason=why, blocked_by=blocker,
            duplicate_of=plan.duplicate_of.get(c.trial_id),
            reconcile=None if blocker is None or c.trial_id in plan.duplicate_of
            else reconcile_eligibility(trials[blocker], trials[c.trial_id]),
        ))  # fmt: skip
    pairs = tuple(sorted(tuple(sorted(p)) for p in plan.conflicts))
    update = {"keeps": tuple(records), "conflicts": pairs}
    return replace(outcome, combination=combination.model_copy(update=update))


def _blocked(
    skip: CombineSkip, applied: Sequence[str], conflicts: AbstractSet[frozenset[str]]
) -> CombineSkip:
    by = next((a for a in applied if frozenset({a, skip.trial_id}) in conflicts), None)
    return skip if by is None else skip.model_copy(update={"blocked_by": by})


def _lost(trial_id: str, skip: CombineSkip | None, fallback: str | None) -> str:
    """Why an offered keep was not delivered: its skip, else the combination."""
    if skip is not None:
        return skip.reason
    lost = "the combination did not hold"
    if fallback is None:
        return lost
    if fallback == trial_id:
        return f"{lost}, nor this change alone"
    return f"{lost}; the fallback re-tested trial {fallback[:8]} alone"


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
    *,
    conflicts: AbstractSet[frozenset[str]] = frozenset(),
) -> CombineOutcome:
    """Combine ``changes`` greedily, re-judge, fall back once (module docstring).

    With the dry merge's ``conflicts`` (S2) a skip names its blocker: the
    first change the greedy merge applied whose pair with it conflicts.
    """
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
    if conflicts:
        skipped = tuple(
            _blocked(s, greedy.measured.applied, conflicts) for s in skipped
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
