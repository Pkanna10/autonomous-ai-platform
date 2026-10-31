"""Tests for ``rank_generated`` (Step 3, U7, D8).

Generated hypotheses keep the model's order; only lessons reorder them:
``score = (1 + lesson_boost) / (1 + position)``. ``expected_gain``,
``provability`` and ``risk`` are ignored (uncalibrated), a ``review`` lesson
is neutral (D10), ties keep the input order, the inputs are not mutated.
"""

from __future__ import annotations

import pytest

from autonomous_ai_agents.common.models import (
    ChangeClass,
    Hypothesis,
    HypothesisSource,
    Lesson,
    VerdictOutcome,
)
from autonomous_ai_agents.optimization.ranking import MAX_LESSON_BOOST, rank_generated


def _idea(
    hid: str, *, gain: float = 0.3, technique_id: str | None = None
) -> Hypothesis:
    return Hypothesis(
        id=hid,
        project_id="p1",
        source=HypothesisSource.novel,
        technique_id=technique_id,
        title=f"idea {hid}",
        rationale="r",
        change_class=ChangeClass.efficiency,
        expected_gain=gain,
        provability=0.9,
        risk=0.1,
    )


def _lesson(outcome: VerdictOutcome, hid: str, weight: float = 1.0) -> Lesson:
    return Lesson(
        project_id="p1", hypothesis_id=hid, outcome=outcome, text="t", weight=weight
    )


def _ids(ranked: tuple[Hypothesis, ...]) -> list[str]:
    return [h.id for h in ranked]


def test_without_lessons_the_model_order_is_kept_whatever_the_claimed_gain() -> None:
    ideas = [_idea("a", gain=0.01), _idea("b", gain=0.9), _idea("c", gain=0.5)]
    ranked = rank_generated(ideas)
    assert _ids(ranked) == ["a", "b", "c"]
    assert [h.score for h in ranked] == pytest.approx([1.0, 1 / 2, 1 / 3])


def test_a_keep_lesson_reorders() -> None:
    ideas = [_idea("a"), _idea("b"), _idea("c"), _idea("d")]
    strong_keep = _lesson(VerdictOutcome.keep, "d", weight=10.0)  # clamped to 0.5
    ranked = rank_generated(ideas, [strong_keep])
    assert _ids(ranked) == ["a", "b", "d", "c"]
    assert ranked[2].score == pytest.approx((1 + MAX_LESSON_BOOST) / 4)


def test_a_keep_lesson_through_the_technique_reorders() -> None:
    ideas = [_idea("a"), _idea("b", technique_id="set-membership")]
    keep = Lesson(
        project_id="p1",
        technique_id="set-membership",
        outcome=VerdictOutcome.keep,
        text="t",
        weight=10.0,
    )
    reject = Lesson(
        project_id="p1",
        hypothesis_id="a",
        outcome=VerdictOutcome.reject,
        text="t",
        weight=10.0,
    )
    ranked = rank_generated(ideas, [keep, reject])
    assert _ids(ranked) == ["b", "a"]
    assert [h.score for h in ranked] == pytest.approx([0.75, 0.5])


def test_a_review_lesson_is_neutral() -> None:
    ideas = [_idea("a"), _idea("b")]
    ranked = rank_generated(ideas, [_lesson(VerdictOutcome.review, "b", 10.0)])
    assert [h.score for h in ranked] == pytest.approx([1.0, 0.5])


def test_ties_keep_the_input_order() -> None:
    ideas = [_idea("a"), _idea("b"), _idea("c")]
    # c: (1 + 0.5) / 3 = 0.5 ties b's 1 / 2.
    ranked = rank_generated(ideas, [_lesson(VerdictOutcome.keep, "c", 10.0)])
    assert _ids(ranked) == ["a", "b", "c"]


def test_the_inputs_are_not_mutated_and_empty_is_empty() -> None:
    ideas = (_idea("a"), _idea("b"))
    rank_generated(ideas)
    assert [h.score for h in ideas] == [0.0, 0.0]
    assert rank_generated(()) == ()
