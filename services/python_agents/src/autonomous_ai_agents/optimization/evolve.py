"""Near-miss compounds (G5b, W4 folded in; D12, D22): pure, no I/O.

Two verdicts form a pair when both are ``inconclusive``, both in the right
direction with a primary gain of at least ``NEAR_MISS_FRACTION`` of their
noise floor, their measured trials changed disjoint files, both are
``efficiency`` class, and neither is a proposal (``idea_types.is_proposal``)
or parked. The gain and the floor are the gain judge's ``JudgeResult.gain``
and ``noise_floor`` on the metric ``judges.primary_metric`` names (relative,
the weakest workload, the calibrated floor included: the calibration raises
the objective's ``min_relative_gain``, which the floor takes its maximum
with). The near miss must be on the primary: its result ``inconclusive``,
no result ``failed`` and no blocking result (one without a metric)
inconclusive, so a trial that is only held back by a guardrail is none.
``find_pair`` returns at most one pair, the best by combined gain/floor
ratio, ties by the two trial ids (sorted), so the input order never matters.

A compound (``compound_hypothesis``) is a hypothesis of its own: source
``lesson`` (D12), ``efficiency``, never a proposal, its id derived from its
parents' trial ids (``compound_id``, so a re-executed node rebuilds it) and
its parents recorded in its tags (``COMPOUND_TAG`` and one
``compound_parent:<trial id>`` each), which the checkpoint round-trips;
``compound_parents`` reads them back and refuses anything else. Lineage: a
compound is judged like any trial, so it is a parent of a later compound
only when it too is an inconclusive near miss (its files are its parents',
so never with one of them), and each pair of trials compounds once
(``used_pairs``).

``ReplayRefusedError`` is why a compound was not built (a cherry-pick conflict,
an unfit parent): the trials node records it as a note, never a trial.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Iterable, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import Final

from autonomous_ai_agents.common.errors import EngineError
from autonomous_ai_agents.common.models import (
    HYPOTHESIS_TAG,
    ChangeClass,
    Hypothesis,
    HypothesisSource,
    JudgeOutcome,
    JudgeResult,
    Trial,
    TrialStatus,
    Verdict,
    VerdictOutcome,
)
from autonomous_ai_agents.optimization.idea_types import is_proposal
from autonomous_ai_agents.optimization.judges import SHADOW_JUDGES

NEAR_MISS_FRACTION: Final = 0.5
"""The least primary gain of a near miss, as a share of its noise floor (D22)."""
COMPOUND_TAG: Final = "compound:replay"
"""The tag every compound carries: built by replay, never by the editor."""
PARENT_KEY: Final = "compound_parent"
"""The tag key of a compound's parent: ``compound_parent:<trial id>``."""
COMPOUND_NAMESPACE: Final = uuid.UUID("9b1f4c2e-6a3d-5e8f-b7c0-1d2e3f4a5b6c")
"""uuid5 namespace of compound ids: ``uuid5(ns, "<first>+<second>")``."""
_TITLE_CHARS: Final = 200


class ReplayRefusedError(EngineError):
    """A compound that was not built: ``reason`` (``conflict`` and the
    ``paths`` git named, or an unfit parent); nothing was left behind."""

    def __init__(self, reason: str, paths: Sequence[str] = ()) -> None:
        self.reason, self.paths = reason, tuple(paths)
        named = f": {', '.join(self.paths)}" if self.paths else ""
        super().__init__(f"{reason}{named}")


@dataclass(frozen=True)
class NearMiss:
    """One near miss: its trial, its hypothesis, its primary gain and its
    gain/floor ratio."""

    trial: Trial
    hypothesis: Hypothesis
    gain: float
    ratio: float


@dataclass(frozen=True)
class CompoundPair:
    """Two near misses; ``first`` has the lower trial id."""

    first: NearMiss
    second: NearMiss

    @property
    def ratio(self) -> float:
        return self.first.ratio + self.second.ratio

    @property
    def key(self) -> frozenset[str]:
        return frozenset({self.first.trial.id, self.second.trial.id})


@dataclass(frozen=True)
class CompoundParents:
    """A compound's two parent trial ids, sorted (read from its tags)."""

    first: str
    second: str


def primary_gain_floor(
    results: Sequence[JudgeResult], primary: str | None
) -> tuple[float | None, float | None]:
    """The (gain, noise floor) of the deciding result on ``primary``, whatever
    its outcome; ``(None, None)`` without one. The round seeds read a trial's
    gain/floor here, so they and the compounds agree (G5b)."""
    found = next(
        (r for r in results if r.judge not in SHADOW_JUDGES and r.metric == primary),
        None,
    )
    return (
        (None, None)
        if found is None or primary is None
        else (found.gain, found.noise_floor)
    )


def _primary_gain(
    results: Sequence[JudgeResult], primary: str
) -> tuple[float, float] | None:
    """The primary (gain, gain/floor) when it alone is held back."""
    deciding = [r for r in results if r.judge not in SHADOW_JUDGES]
    found = next((r for r in deciding if r.metric == primary), None)
    if found is None or found.outcome is not JudgeOutcome.inconclusive:
        return None
    blocked = any(
        r.outcome is JudgeOutcome.failed
        or (r.metric is None and r.outcome is JudgeOutcome.inconclusive)
        for r in deciding
    )
    gain, floor = found.gain, found.noise_floor
    if blocked or gain is None or floor is None or not floor > 0:
        return None
    ratio = gain / floor
    usable = math.isfinite(ratio) and ratio >= NEAR_MISS_FRACTION
    return (gain, ratio) if usable else None


def near_miss(
    verdict: Verdict,
    trial: Trial,
    hypothesis: Hypothesis,
    *,
    primary: str | None,
    parked: AbstractSet[str] = frozenset(),
) -> NearMiss | None:
    """``verdict``'s near miss (module docstring), or ``None``."""
    usable = (
        primary is not None
        and verdict.outcome is VerdictOutcome.inconclusive
        and verdict.trial_id == trial.id
        and verdict.hypothesis_id == trial.hypothesis_id == hypothesis.id
        and not verdict.violations
        and trial.status is TrialStatus.measured
        and not trial.violations
        and trial.commit is not None
        and bool(trial.touched_paths)
        and verdict.change_class is hypothesis.change_class is ChangeClass.efficiency
        and not is_proposal(hypothesis)
        and hypothesis.id not in parked
        and HYPOTHESIS_TAG.fullmatch(f"{PARENT_KEY}:{trial.id}") is not None
    )
    found = _primary_gain(verdict.judge_results, str(primary)) if usable else None
    return None if found is None else NearMiss(trial, hypothesis, *found)


def _disjoint(a: Trial, b: Trial) -> bool:
    """No shared path, case-folded (a case-insensitive file system shares one)."""
    return not {p.casefold() for p in a.touched_paths} & {
        p.casefold() for p in b.touched_paths
    }


def find_pair(
    verdicts: Iterable[Verdict],
    trials: Iterable[Trial],
    hypotheses: Iterable[Hypothesis],
    *,
    primary: str | None,
    parked: AbstractSet[str] = frozenset(),
    used: AbstractSet[frozenset[str]] = frozenset(),
) -> CompoundPair | None:
    """The best pair of this run's near misses not compounded yet, or ``None``."""
    by_trial = {trial.id: trial for trial in trials}
    by_hypothesis = {hypothesis.id: hypothesis for hypothesis in hypotheses}
    misses: dict[str, NearMiss] = {}
    for verdict in verdicts:
        trial = by_trial.get(verdict.trial_id)
        hypothesis = by_hypothesis.get(verdict.hypothesis_id)
        if trial is None or hypothesis is None or trial.id in misses:
            continue
        found = near_miss(verdict, trial, hypothesis, primary=primary, parked=parked)
        if found is not None:
            misses[trial.id] = found
    ordered = [misses[key] for key in sorted(misses)]
    pairs = [
        CompoundPair(a, b)
        for index, a in enumerate(ordered)
        for b in ordered[index + 1 :]
        if _disjoint(a.trial, b.trial)
    ]
    fresh = [pair for pair in pairs if pair.key not in used]
    return min(
        fresh,
        key=lambda p: (-p.ratio, p.first.trial.id, p.second.trial.id),
        default=None,
    )


def compound_id(first: str, second: str) -> str:
    """The compound's deterministic id, whatever the order of its parents."""
    low, high = sorted((first, second))
    return str(uuid.uuid5(COMPOUND_NAMESPACE, f"{low}+{high}"))


def compound_hypothesis(pair: CompoundPair) -> Hypothesis:
    """``pair`` as a hypothesis of its own (module docstring)."""
    a, b = pair.first, pair.second
    title = f"compound: {a.hypothesis.title} + {b.hypothesis.title}"
    hotspots = dict.fromkeys((*a.hypothesis.hotspot_ids, *b.hypothesis.hotspot_ids))
    return Hypothesis(
        id=compound_id(a.trial.id, b.trial.id),
        project_id=a.hypothesis.project_id,
        hotspot_ids=tuple(hotspots),
        source=HypothesisSource.lesson,
        title=title[:_TITLE_CHARS],
        rationale=(
            f"replays two near misses (gain/floor {a.ratio:.2f} and {b.ratio:.2f})"
            " whose trials changed disjoint files; judged from scratch"
        ),
        change_class=ChangeClass.efficiency,
        expected_gain=a.gain + b.gain,
        provability=min(a.hypothesis.provability, b.hypothesis.provability),
        risk=max(a.hypothesis.risk, b.hypothesis.risk),
        tags=(COMPOUND_TAG, f"{PARENT_KEY}:{a.trial.id}", f"{PARENT_KEY}:{b.trial.id}"),
    )


def compound_parents(hypothesis: Hypothesis) -> CompoundParents | None:
    """``hypothesis``'s parents when it is the engine's own compound record:
    source ``lesson``, ``COMPOUND_TAG``, exactly two distinct parent tags and
    the id derived from them; anything else is ``None``."""
    prefix = f"{PARENT_KEY}:"
    parents = sorted(
        {t[len(prefix) :] for t in hypothesis.tags if t.startswith(prefix)}
    )
    count = sum(1 for tag in hypothesis.tags if tag.startswith(prefix))
    if (
        hypothesis.source is not HypothesisSource.lesson
        or COMPOUND_TAG not in hypothesis.tags
        or len(parents) != 2
        or count != 2
        or hypothesis.id != compound_id(*parents)
    ):
        return None
    return CompoundParents(*parents)


def used_pairs(hypotheses: Iterable[Hypothesis]) -> frozenset[frozenset[str]]:
    """The parent pairs of every compound among ``hypotheses``."""
    found = (compound_parents(h) for h in hypotheses)
    return frozenset(frozenset({p.first, p.second}) for p in found if p is not None)
