"""The idea pipeline's deterministic stages, S4a and S4b (Step 3 Wave 2, N3b;
spec amendment 3.4, D51-D53, D8 amended).

Pure functions: no model, no I/O, nothing random.

- ``deterministic_filter`` (S4a, before the reviewer): every lens or leap
  idea needs an anchor; on a time objective its Amdahl ceiling (the anchor's
  own cumulative share, filled in by the caller from ``amdahl_ceiling``) must
  reach ``multiplier x floor``; an idea whose structural ``signature`` repeats
  an earlier gate-passed one is a duplicate; and it must be non-obvious: no
  S1 signature, no title already tried (``avoid``) or learnt (lesson titles),
  no shown technique (matched mode). S1 ideas pass through untouched, first.
- ``portfolio`` (S4b, after the reviewer): ``_sift``'s title and class
  filters run first (a repeated title key is dropped, a ``novel`` idea is
  placed after the portfolio, where ``_sift`` parks it), then 3-5 non-obvious
  ideas are picked by quotas (one per lane, one per anchor, one per primary
  cell, then at least one ``transformational``, swapped in for the pick that
  blocks it), lanes visited in the run's
  ``rotation``, model order within a lane; a quota that blocks the minimum is
  relaxed in reverse priority order, noted, and still breaks ties. The result
  interleaves one obvious and two non-obvious ideas per round of three.

No model-written number (``expected_gain``, ``provability``, ``risk``) and no
reviewer verdict decides anything here (D8 amended).
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable, Collection, Sequence
from typing import Final

from autonomous_ai_agents.clients.structured import shorten, shown
from autonomous_ai_agents.common.models import (
    ChangeClass,
    Lesson,
    Objective,
    ObjectiveKind,
)
from autonomous_ai_agents.optimization.idea_types import (
    GenerateEvent,
    IdeaCandidate,
    Lane,
    Tier,
)

TIME_OBJECTIVES: Final = frozenset({ObjectiveKind.runtime, ObjectiveKind.throughput})
"""The objectives the Amdahl gate applies to (D51); memory and the rest pass."""

OBVIOUS_PER_ROUND: Final = 1
NON_OBVIOUS_PER_ROUND: Final = 2
"""``O1 N1 N2 O2 N3 N4 ...``: one round of ``max_hypotheses_per_round`` (3)."""

Signature = tuple[tuple[str, ...], str, tuple[str, ...]]
"""``(anchor or hotspots, mechanism, sorted morph cells)``, the anchor first."""


def _title_key(title: str) -> str:
    """A title as ``_title_key`` (``nodes.py``) compares it."""
    return " ".join(title.split()).casefold()


def signature(idea: IdeaCandidate) -> Signature:
    """The structural signature (D52): ``("anchor", path, qualname)`` leads
    it; an idea with no anchor (S1 only) stands on its sorted hotspot ids."""
    where: tuple[str, ...]
    if idea.anchor is not None:
        where = ("anchor", idea.anchor.path, idea.anchor.qualname)
    else:
        where = ("hotspots", *sorted(idea.hotspot_ids))
    cells = tuple(sorted(cell.value for cell in idea.morph_cells))
    return where, idea.mechanism.value, cells


# --------------------------------------------------------------------------
# S4a: the gate, the dedup and the non-obvious test (D51, D52)
# --------------------------------------------------------------------------


def deterministic_filter(
    obvious: Sequence[IdeaCandidate],
    others: Sequence[IdeaCandidate],
    *,
    floor: float,
    objective: Objective,
    avoid: Collection[str],
    lesson_titles: Collection[str],
    multiplier: float,
    notes: list[str],
    shown_slugs: Collection[str] = (),
    events: list[GenerateEvent] | None = None,
) -> tuple[IdeaCandidate, ...]:
    """``obvious`` unchanged, then the ``others`` that survive, in order.

    ``floor`` is the objective's calibrated ``min_relative_gain``; each drop
    is noted and, when ``events`` is given, appended as an ``idea_dropped``
    event whose ``reason`` is a code word.
    """
    if not 0 <= floor <= 1:
        raise ValueError(f"floor must be a share in [0, 1], got {floor}")
    if not (math.isfinite(multiplier) and multiplier >= 1):
        raise ValueError(f"multiplier must be finite and >= 1, got {multiplier}")
    gated = objective.kind in TIME_OBJECTIVES
    taken = {signature(idea): idea for idea in reversed(obvious)}
    avoided = {_title_key(title) for title in avoid}
    learnt = {_title_key(title) for title in lesson_titles}
    seen: dict[Signature, IdeaCandidate] = {}
    kept: list[IdeaCandidate] = []
    for idea in others:
        found = _drop_reason(idea, gated, floor, multiplier)
        mark = signature(idea)
        if found is None and mark in seen:
            found = "duplicate", f"duplicate of {shown(seen[mark].title)}"
        elif found is None:
            seen[mark] = idea
            found = _obvious_reason(idea, taken.get(mark), avoided, learnt,
                                    shown_slugs)  # fmt: skip
        if found is None:
            kept.append(idea)
            continue
        code, why = found
        note = f"filter: dropped idea {shown(idea.title)} ({idea.lane.value}): {why}"
        notes.append(note)
        if events is not None:
            data: dict[str, str | None] = {"lane": idea.lane.value, "reason": code,
                                           "title": shorten(idea.title)}  # fmt: skip
            events.append(GenerateEvent(code="idea_dropped", message=note, data=data))
    return (*obvious, *kept)


def _drop_reason(
    idea: IdeaCandidate, gated: bool, floor: float, multiplier: float
) -> tuple[str, str] | None:
    if idea.anchor is None:
        return "no_anchor", "it has no anchor"
    if not gated:
        return None
    if idea.ceiling is None:
        return "ceiling_unknown", "its Amdahl ceiling is unknown"
    if idea.ceiling < multiplier * floor:
        return "below_gate", (
            f"its ceiling {idea.ceiling:.1%} is below {multiplier:g} x the floor "
            f"{floor:.1%}"
        )
    return None


def _obvious_reason(
    idea: IdeaCandidate,
    twin: IdeaCandidate | None,
    avoided: set[str],
    learnt: set[str],
    shown_slugs: Collection[str],
) -> tuple[str, str] | None:
    key = _title_key(idea.title)
    if twin is not None:
        return (
            "obvious_signature",
            f"same signature as obvious idea {shown(twin.title)}",
        )
    if key in avoided:
        return "avoided_title", "its title is already tried (avoid_titles)"
    if key in learnt:
        return "lesson_title", "its title is a lesson title"
    if idea.technique_slug is not None and idea.technique_slug in shown_slugs:
        return "shown_technique", f"it names the shown technique {idea.technique_slug}"
    return None


# --------------------------------------------------------------------------
# S4b: the portfolio (D53)
# --------------------------------------------------------------------------

_Quota = tuple[str, Callable[[IdeaCandidate], object]]
_QUOTAS: Final[tuple[_Quota, ...]] = (
    ("lane", lambda idea: idea.lane),
    ("anchor", lambda idea: idea.anchor or idea.id),
    ("primary-cell", lambda idea: idea.morph_cells[0]),
)
"""The quotas in priority order: at most one picked idea per key."""


def portfolio(
    obvious: Sequence[IdeaCandidate],
    candidates: Sequence[IdeaCandidate],
    *,
    rotation: Sequence[Lane],
    minimum: int,
    maximum: int,
    notes: list[str],
) -> tuple[IdeaCandidate, ...]:
    """The interleaved obvious and picked ideas, then any ``novel`` ones."""
    if not 1 <= minimum <= maximum:
        raise ValueError(f"need 1 <= minimum <= maximum, got {minimum}, {maximum}")
    titles: set[str] = set()
    parked: list[IdeaCandidate] = []

    def admitted(idea: IdeaCandidate) -> bool:
        key = _title_key(idea.title)
        if key in titles:
            notes.append(f"portfolio: dropped repeated idea {shown(idea.title)}")
            return False
        titles.add(key)
        if idea.change_class is ChangeClass.novel:
            parked.append(idea)
            notes.append(f"portfolio: novel idea {shown(idea.title)} placed after "
                         "the portfolio (needs approval)")  # fmt: skip
            return False
        return True

    olds = [idea for idea in obvious if admitted(idea)]
    pool = [idea for idea in candidates if admitted(idea)]
    picked = [pool[i] for i in _pick(pool, rotation, minimum, maximum, notes)]
    rounds: list[IdeaCandidate] = []
    while olds or picked:
        rounds += olds[:OBVIOUS_PER_ROUND] + picked[:NON_OBVIOUS_PER_ROUND]
        del olds[:OBVIOUS_PER_ROUND], picked[:NON_OBVIOUS_PER_ROUND]
    return (*rounds, *parked)


def _pick(
    pool: list[IdeaCandidate],
    rotation: Sequence[Lane],
    minimum: int,
    maximum: int,
    notes: list[str],
) -> list[int]:
    """Indexes into ``pool`` in pick order (rotation, then model order)."""
    lanes = dict.fromkeys([*rotation, *(idea.lane for idea in pool)])
    queues = [[i for i, idea in enumerate(pool) if idea.lane is lane] for lane in lanes]
    active = list(_QUOTAS)
    picked: list[int] = []

    def misses(i: int, among: list[int], quotas: Sequence[_Quota]) -> list[bool]:
        return [any(key(pool[i]) == key(pool[p]) for p in among) for _, key in quotas]

    def fits(i: int, among: list[int]) -> bool:
        return not any(misses(i, among, active))

    def fill(target: int) -> None:
        progress = True
        while progress and len(picked) < target:
            progress = False
            for queue in queues:
                ready = [i for i in queue if i not in picked and fits(i, picked)]
                if ready and len(picked) < target:
                    # A relaxed quota still breaks ties, in priority order.
                    picked.append(
                        min(ready, key=lambda i: (misses(i, picked, _QUOTAS), i))
                    )
                    progress = True

    fill(maximum)
    while len(picked) < min(minimum, len(pool)):
        name, _ = active.pop()
        notes.append(
            f"portfolio: relaxed the one-per-{name} quota to reach {minimum} ideas"
        )
        fill(minimum)
    if not pool:
        notes.append("portfolio: no non-obvious idea survives")
    elif len(pool) < minimum:
        notes.append(
            f"portfolio: only {len(pool)} non-obvious idea(s) survive; all are taken"
        )
    _tier(pool, [i for queue in queues for i in queue], picked, maximum, notes, fits)
    return picked


def _tier(
    pool: list[IdeaCandidate],
    visit: list[int],
    picked: list[int],
    maximum: int,
    notes: list[str],
    fits: Callable[[int, list[int]], bool],
) -> None:
    """At least one ``transformational`` idea when one survives, the last
    quota (D53): added at the end when there is room and it fits, else in
    place of the latest pick whose removal lets it fit (latest first, so the
    earlier lanes of the rotation keep their picks)."""
    bold = [i for i in visit if pool[i].tier is Tier.transformational]
    if not bold or any(i in picked for i in bold):
        return
    for i in bold:
        if len(picked) < maximum and fits(i, picked):
            picked.append(i)
            notes.append(f"portfolio: {shown(pool[i].title)} (transformational) "
                         "added (tier quota)")  # fmt: skip
            return
        for at in reversed(range(len(picked))):
            if fits(i, picked[:at] + picked[at + 1 :]):
                notes.append(f"portfolio: {shown(pool[i].title)} (transformational) "
                             f"replaces {shown(pool[picked[at]].title)} (tier quota)")  # fmt: skip
                picked[at] = i
                return
    notes.append(
        "portfolio: relaxed the tier quota: no transformational idea fits the others"
    )


# --------------------------------------------------------------------------
# Lesson titles and the rotation
# --------------------------------------------------------------------------


def lesson_titles(lessons: Sequence[Lesson]) -> frozenset[str]:
    """The titles in lesson texts ``"<context> -> <title>: <outcome>[ (<gain>)]"``
    (``lessons.py``), parsed on the first ``" -> "`` and the last
    ``": <outcome>"``, so a title holding ``": "`` survives; others skipped."""
    found: set[str] = set()
    for lesson in lessons:
        outcome = re.escape(lesson.outcome.value)
        match = re.fullmatch(
            rf"(?s).*? -> (?P<title>.*): {outcome}(?: \([^()]*\))?", lesson.text
        )
        if match is not None and match["title"].strip():
            found.add(match["title"])
    return frozenset(found)


def rotation(seed: str, lanes: Sequence[Lane]) -> tuple[Lane, ...]:
    """A deterministic permutation of the distinct ``lanes`` for ``seed`` (D53):
    each lane sorts by the SHA-256 of the seed and its name."""

    def rank(lane: Lane) -> str:
        return hashlib.sha256(f"{seed}\0{lane.value}".encode()).hexdigest()

    return tuple(sorted(dict.fromkeys(lanes), key=rank))
