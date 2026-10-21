"""Tests for hypothesis ranking (Step 1, unit U3).

Pure functions: ``score = expected_gain * provability * (1 - risk) *
(1 + lesson_boost)``, where lessons learned from earlier verdicts nudge the
score up (keeps) or down (rejects) by 0.1 per lesson, weighted, clamped to
[-0.5, 0.5]. Ranking never mutates its inputs.
"""

from __future__ import annotations

import pytest

from autonomous_ai_agents.common.models import (
    ChangeClass,
    Hypothesis,
    HypothesisSource,
    HypothesisStatus,
    Lesson,
    VerdictOutcome,
    new_id,
)
from autonomous_ai_agents.optimization.ranking import (
    LESSON_STEP,
    MAX_LESSON_BOOST,
    lesson_boost,
    lesson_matches,
    rank_hypotheses,
    score_hypothesis,
)

PROJECT_ID = new_id()
TECHNIQUE_ID = new_id()


def _hypothesis(
    *,
    technique_id: str | None = TECHNIQUE_ID,
    expected_gain: float = 0.4,
    provability: float = 0.9,
    risk: float = 0.1,
    title: str = "Cache CLIP embeddings to disk",
) -> Hypothesis:
    return Hypothesis(
        project_id=PROJECT_ID,
        source=HypothesisSource.playbook,
        technique_id=technique_id,
        title=title,
        rationale="Encoder is frozen; 42% of step time recomputes it.",
        change_class=ChangeClass.efficiency,
        expected_gain=expected_gain,
        provability=provability,
        risk=risk,
    )


def _lesson(
    outcome: VerdictOutcome,
    *,
    technique_id: str | None = None,
    hypothesis_id: str | None = None,
    weight: float = 1.0,
) -> Lesson:
    return Lesson(
        project_id=PROJECT_ID,
        technique_id=technique_id,
        hypothesis_id=hypothesis_id,
        outcome=outcome,
        text=f"lesson: {outcome.value}",
        weight=weight,
    )


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def test_lesson_matches_by_technique_id() -> None:
    """
    GIVEN a hypothesis derived from a technique
    WHEN a lesson carries the same technique_id
    THEN it matches
    """
    hypothesis = _hypothesis()

    assert lesson_matches(
        hypothesis, _lesson(VerdictOutcome.keep, technique_id=TECHNIQUE_ID)
    )
    assert not lesson_matches(
        hypothesis, _lesson(VerdictOutcome.keep, technique_id=new_id())
    )


def test_lesson_matches_by_hypothesis_id() -> None:
    """
    GIVEN a hypothesis without a technique
    WHEN a lesson carries the hypothesis id
    THEN it matches, regardless of technique
    """
    hypothesis = _hypothesis(technique_id=None)

    assert lesson_matches(
        hypothesis, _lesson(VerdictOutcome.keep, hypothesis_id=hypothesis.id)
    )
    assert not lesson_matches(
        hypothesis, _lesson(VerdictOutcome.keep, hypothesis_id=new_id())
    )


def test_lesson_without_technique_does_not_match_hypothesis_without_technique() -> None:
    """
    GIVEN a hypothesis whose technique_id is None
    WHEN a lesson's technique_id is also None (and ids differ)
    THEN they do not match (None never matches None)
    """
    hypothesis = _hypothesis(technique_id=None)

    assert not lesson_matches(hypothesis, _lesson(VerdictOutcome.keep))


# ---------------------------------------------------------------------------
# lesson_boost
# ---------------------------------------------------------------------------


def test_lesson_boost_is_zero_without_lessons() -> None:
    """
    GIVEN no lessons
    WHEN the boost is computed
    THEN it is 0.0
    """
    assert lesson_boost(_hypothesis(), ()) == 0.0
    assert lesson_boost(_hypothesis(), []) == 0.0


def test_lesson_boost_is_zero_when_no_lesson_matches() -> None:
    """
    GIVEN lessons about other techniques and hypotheses
    WHEN the boost is computed
    THEN it is 0.0
    """
    lessons = (
        _lesson(VerdictOutcome.keep, technique_id=new_id()),
        _lesson(VerdictOutcome.reject, hypothesis_id=new_id()),
    )

    assert lesson_boost(_hypothesis(), lessons) == 0.0


def test_lesson_boost_adds_keeps_and_subtracts_rejects() -> None:
    """
    GIVEN two keep lessons and one reject lesson for the technique
    WHEN the boost is computed
    THEN it is 0.1 * 2 - 0.1 * 1 = 0.1
    """
    lessons = (
        _lesson(VerdictOutcome.keep, technique_id=TECHNIQUE_ID),
        _lesson(VerdictOutcome.keep, technique_id=TECHNIQUE_ID),
        _lesson(VerdictOutcome.reject, technique_id=TECHNIQUE_ID),
    )

    assert lesson_boost(_hypothesis(), lessons) == pytest.approx(0.1)


def test_lesson_boost_matches_through_both_routes() -> None:
    """
    GIVEN one lesson matching by technique and one by hypothesis id
    WHEN the boost is computed
    THEN both count
    """
    hypothesis = _hypothesis()
    lessons = (
        _lesson(VerdictOutcome.keep, technique_id=TECHNIQUE_ID),
        _lesson(VerdictOutcome.keep, hypothesis_id=hypothesis.id),
    )

    assert lesson_boost(hypothesis, lessons) == pytest.approx(0.2)


@pytest.mark.parametrize(
    "outcome", [VerdictOutcome.inconclusive, VerdictOutcome.needs_approval]
)
def test_lesson_boost_ignores_non_decisive_outcomes(outcome: VerdictOutcome) -> None:
    """
    GIVEN a matching lesson whose outcome is neither keep nor reject
    WHEN the boost is computed
    THEN it contributes nothing
    """
    lessons = (_lesson(outcome, technique_id=TECHNIQUE_ID),)

    assert lesson_boost(_hypothesis(), lessons) == 0.0


def test_lesson_boost_is_clamped_to_plus_half() -> None:
    """
    GIVEN seven keep lessons (raw boost 0.7)
    WHEN the boost is computed
    THEN it is clamped to +0.5
    """
    lessons = tuple(
        _lesson(VerdictOutcome.keep, technique_id=TECHNIQUE_ID) for _ in range(7)
    )

    assert lesson_boost(_hypothesis(), lessons) == pytest.approx(MAX_LESSON_BOOST)
    assert MAX_LESSON_BOOST == 0.5


def test_lesson_boost_is_clamped_to_minus_half() -> None:
    """
    GIVEN seven reject lessons (raw boost -0.7)
    WHEN the boost is computed
    THEN it is clamped to -0.5
    """
    lessons = tuple(
        _lesson(VerdictOutcome.reject, technique_id=TECHNIQUE_ID) for _ in range(7)
    )

    assert lesson_boost(_hypothesis(), lessons) == pytest.approx(-MAX_LESSON_BOOST)


def test_lesson_boost_exactly_at_the_clamp_is_unchanged() -> None:
    """
    GIVEN five keep lessons (raw boost exactly 0.5)
    WHEN the boost is computed
    THEN it is 0.5
    """
    lessons = tuple(
        _lesson(VerdictOutcome.keep, technique_id=TECHNIQUE_ID) for _ in range(5)
    )

    assert lesson_boost(_hypothesis(), lessons) == pytest.approx(0.5)


def test_lesson_weight_scales_its_contribution() -> None:
    """
    GIVEN a keep lesson with weight 2.5 and a reject lesson with weight 0.5
    WHEN the boost is computed
    THEN each contributes 0.1 * weight: 0.25 - 0.05 = 0.2
    """
    lessons = (
        _lesson(VerdictOutcome.keep, technique_id=TECHNIQUE_ID, weight=2.5),
        _lesson(VerdictOutcome.reject, technique_id=TECHNIQUE_ID, weight=0.5),
    )

    assert LESSON_STEP == 0.1
    assert lesson_boost(_hypothesis(), lessons) == pytest.approx(0.2)


def test_heavy_weight_is_still_clamped() -> None:
    """
    GIVEN a single keep lesson with weight 100
    WHEN the boost is computed
    THEN it is clamped to +0.5
    """
    lessons = (_lesson(VerdictOutcome.keep, technique_id=TECHNIQUE_ID, weight=100.0),)

    assert lesson_boost(_hypothesis(), lessons) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# score_hypothesis
# ---------------------------------------------------------------------------


def test_score_hypothesis_without_lessons() -> None:
    """
    GIVEN expected_gain 0.4, provability 0.9, risk 0.1 and no lessons
    WHEN the score is computed
    THEN it is 0.4 * 0.9 * 0.9 = 0.324
    """
    assert score_hypothesis(_hypothesis()) == pytest.approx(0.324)
    assert score_hypothesis(_hypothesis(), ()) == pytest.approx(0.324)


def test_score_hypothesis_applies_lesson_boost() -> None:
    """
    GIVEN the same hypothesis and one matching keep lesson
    WHEN the score is computed
    THEN it is 0.324 * (1 + 0.1)
    """
    lessons = (_lesson(VerdictOutcome.keep, technique_id=TECHNIQUE_ID),)

    assert score_hypothesis(_hypothesis(), lessons) == pytest.approx(0.324 * 1.1)


def test_score_hypothesis_applies_negative_lesson_boost() -> None:
    """
    GIVEN one matching reject lesson
    WHEN the score is computed
    THEN it is 0.324 * (1 - 0.1)
    """
    lessons = (_lesson(VerdictOutcome.reject, technique_id=TECHNIQUE_ID),)

    assert score_hypothesis(_hypothesis(), lessons) == pytest.approx(0.324 * 0.9)


@pytest.mark.parametrize(
    ("expected_gain", "provability", "risk"),
    [(0.0, 0.9, 0.1), (0.4, 0.0, 0.1), (0.4, 0.9, 1.0)],
    ids=["no_gain", "unprovable", "certain_to_break"],
)
def test_score_hypothesis_is_zero_when_any_factor_is_zero(
    expected_gain: float, provability: float, risk: float
) -> None:
    """
    GIVEN a hypothesis with no expected gain, no provability or full risk
    WHEN the score is computed
    THEN it is 0 even with keep lessons behind it
    """
    lessons = (_lesson(VerdictOutcome.keep, technique_id=TECHNIQUE_ID),)
    hypothesis = _hypothesis(
        expected_gain=expected_gain, provability=provability, risk=risk
    )

    assert score_hypothesis(hypothesis, lessons) == 0.0


def test_score_hypothesis_ignores_the_stored_score() -> None:
    """
    GIVEN a hypothesis whose stored score is stale
    WHEN the score is computed
    THEN the stored value plays no part
    """
    stale = _hypothesis().model_copy(update={"score": 99.0})

    assert score_hypothesis(stale) == pytest.approx(0.324)


# ---------------------------------------------------------------------------
# rank_hypotheses
# ---------------------------------------------------------------------------


def test_rank_hypotheses_orders_by_score_descending() -> None:
    """
    GIVEN three hypotheses with different scores, given in ascending order
    WHEN ranked
    THEN they come back best first with scores filled in
    """
    low = _hypothesis(expected_gain=0.1, title="low")
    mid = _hypothesis(expected_gain=0.2, title="mid")
    high = _hypothesis(expected_gain=0.4, title="high")

    ranked = rank_hypotheses([low, mid, high])

    assert isinstance(ranked, tuple)
    assert [h.title for h in ranked] == ["high", "mid", "low"]
    assert [h.score for h in ranked] == pytest.approx([0.324, 0.162, 0.081])
    assert ranked[0].score > ranked[1].score > ranked[2].score


def test_rank_hypotheses_keeps_input_order_on_ties() -> None:
    """
    GIVEN four hypotheses with identical ranking inputs
    WHEN ranked
    THEN the input order is preserved (stable sort)
    """
    hypotheses = [_hypothesis(title=f"h{i}") for i in range(4)]

    ranked = rank_hypotheses(hypotheses)

    assert [h.id for h in ranked] == [h.id for h in hypotheses]
    assert len({h.score for h in ranked}) == 1


def test_rank_hypotheses_ties_stay_stable_among_mixed_scores() -> None:
    """
    GIVEN tied hypotheses interleaved with a better and a worse one
    WHEN ranked
    THEN the tied ones keep their relative input order
    """
    tie_a = _hypothesis(expected_gain=0.2, title="tie_a")
    best = _hypothesis(expected_gain=0.5, title="best")
    tie_b = _hypothesis(expected_gain=0.2, title="tie_b")
    worst = _hypothesis(expected_gain=0.05, title="worst")

    ranked = rank_hypotheses((tie_a, best, tie_b, worst))

    assert [h.title for h in ranked] == ["best", "tie_a", "tie_b", "worst"]


def test_rank_hypotheses_lessons_can_reorder() -> None:
    """
    GIVEN two near-equal hypotheses and a reject lesson against the leader
    WHEN ranked with those lessons
    THEN the other hypothesis moves ahead
    """
    other_technique = new_id()
    leader = _hypothesis(expected_gain=0.41, title="leader")
    runner_up = _hypothesis(
        expected_gain=0.40, technique_id=other_technique, title="runner_up"
    )
    lessons = (_lesson(VerdictOutcome.reject, technique_id=TECHNIQUE_ID),)

    assert [h.title for h in rank_hypotheses((leader, runner_up))] == [
        "leader",
        "runner_up",
    ]
    assert [h.title for h in rank_hypotheses((leader, runner_up), lessons)] == [
        "runner_up",
        "leader",
    ]


def test_rank_hypotheses_returns_copies_and_does_not_mutate_inputs() -> None:
    """
    GIVEN hypotheses with the default score of 0
    WHEN ranked
    THEN the inputs still have score 0 and the results are new objects with
         the score set and every other field unchanged
    """
    original = _hypothesis()
    inputs = [original]

    ranked = rank_hypotheses(inputs)

    assert original.score == 0.0
    assert inputs == [original]
    assert ranked[0] is not original
    assert ranked[0].score == pytest.approx(0.324)
    assert ranked[0].model_dump(exclude={"score"}) == original.model_dump(
        exclude={"score"}
    )
    assert ranked[0].status is HypothesisStatus.proposed


def test_rank_hypotheses_empty_input() -> None:
    """
    GIVEN no hypotheses
    WHEN ranked
    THEN an empty tuple is returned, with or without lessons
    """
    assert rank_hypotheses(()) == ()
    assert rank_hypotheses([], (_lesson(VerdictOutcome.keep),)) == ()


def test_rank_hypotheses_is_deterministic() -> None:
    """
    GIVEN the same inputs
    WHEN ranked twice
    THEN the results are equal (pure function)
    """
    hypotheses = [_hypothesis(expected_gain=g) for g in (0.3, 0.1, 0.2)]
    lessons = (_lesson(VerdictOutcome.keep, technique_id=TECHNIQUE_ID),)

    assert rank_hypotheses(hypotheses, lessons) == rank_hypotheses(hypotheses, lessons)
