"""Hypothesis ranking: which ideas the engine trials first.

Pure functions, no I/O. The score is::

    score = expected_gain * provability * (1 - risk) * (1 + lesson_boost)

where ``lesson_boost`` sums what earlier verdicts taught about the same
technique or hypothesis: each ``keep`` lesson adds ``LESSON_STEP * weight``,
each ``reject`` subtracts it, other outcomes are ignored, and the total is
clamped to ``[-MAX_LESSON_BOOST, MAX_LESSON_BOOST]`` so no amount of history
can swamp the hypothesis's own merit.

Generated hypotheses (Step 3, D8) rank by ``rank_generated`` instead::

    score = (1 + lesson_boost) / (1 + position)

where ``position`` is the hypothesis's index in the model's order: that order
is the only measured signal (hit@1 19-21/22 in E3), while a generated
``expected_gain`` is uncalibrated, so only lessons reorder generated ideas.
A ``review`` lesson, like every outcome but ``keep`` and ``reject``, is
neutral (D10).
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


def rank_generated(
    hypotheses: Sequence[Hypothesis], lessons: Sequence[Lesson] = ()
) -> tuple[Hypothesis, ...]:
    """Return copies of generated ``hypotheses`` (model order) with ``score``
    filled as ``(1 + lesson_boost) / (1 + position)``, best first (D8).

    Ties keep their input order (stable sort). The inputs are not mutated.
    """
    scored = [
        hypothesis.model_copy(
            update={"score": (1.0 + lesson_boost(hypothesis, lessons)) / (1 + position)}
        )
        for position, hypothesis in enumerate(hypotheses)
    ]
    return tuple(sorted(scored, key=lambda scored_one: scored_one.score, reverse=True))
