"""Hypothesis ranking: which ideas the engine trials first.

Pure functions, no I/O. The score is::

    score = expected_gain * provability * (1 - risk) * (1 + lesson_boost)

where ``lesson_boost`` sums what earlier verdicts taught about the same
technique or hypothesis: each ``keep`` lesson adds ``LESSON_STEP * weight``,
each ``reject`` subtracts it, other outcomes are ignored, and the total is
clamped to ``[-MAX_LESSON_BOOST, MAX_LESSON_BOOST]`` so no amount of history
can swamp the hypothesis's own merit.
"""

from __future__ import annotations

from collections.abc import Sequence

from autonomous_ai_agents.common.models import Hypothesis, Lesson, VerdictOutcome

LESSON_STEP = 0.1
"""Boost contributed by one keep (or removed by one reject) lesson of weight 1."""

MAX_LESSON_BOOST = 0.5
"""Absolute bound on the lesson boost, in either direction."""


def lesson_matches(hypothesis: Hypothesis, lesson: Lesson) -> bool:
    """Return True when ``lesson`` is about ``hypothesis``.

    A lesson matches through its technique (when the hypothesis has one) or
    through the hypothesis id itself. ``None`` never matches ``None``.
    """
    same_technique = (
        hypothesis.technique_id is not None
        and lesson.technique_id == hypothesis.technique_id
    )
    return same_technique or lesson.hypothesis_id == hypothesis.id


def lesson_boost(hypothesis: Hypothesis, lessons: Sequence[Lesson]) -> float:
    """Return the clamped, weighted boost the matching lessons give ``hypothesis``."""
    raw = 0.0
    for lesson in lessons:
        if not lesson_matches(hypothesis, lesson):
            continue
        if lesson.outcome is VerdictOutcome.keep:
            raw += LESSON_STEP * lesson.weight
        elif lesson.outcome is VerdictOutcome.reject:
            raw -= LESSON_STEP * lesson.weight
    return max(-MAX_LESSON_BOOST, min(MAX_LESSON_BOOST, raw))


def score_hypothesis(hypothesis: Hypothesis, lessons: Sequence[Lesson] = ()) -> float:
    """Return the ranking score of ``hypothesis`` given the lessons so far.

    The stored ``hypothesis.score`` is ignored; the score is recomputed from
    expected gain, provability, risk and the lesson boost.
    """
    merit = hypothesis.expected_gain * hypothesis.provability * (1.0 - hypothesis.risk)
    return merit * (1.0 + lesson_boost(hypothesis, lessons))


def rank_hypotheses(
    hypotheses: Sequence[Hypothesis], lessons: Sequence[Lesson] = ()
) -> tuple[Hypothesis, ...]:
    """Return copies of ``hypotheses`` with ``score`` filled, best first.

    Ties keep their input order (stable sort). The inputs are not mutated.
    """
    scored = [
        hypothesis.model_copy(update={"score": score_hypothesis(hypothesis, lessons)})
        for hypothesis in hypotheses
    ]
    return tuple(sorted(scored, key=lambda scored_one: scored_one.score, reverse=True))
