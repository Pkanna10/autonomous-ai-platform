"""Tests for the lessons store helpers (Step 1, unit U3).

``lesson_from_verdict`` turns a verdict into the ``Lesson`` the next
hypothesis ranking reads; ``lessons_from_verdicts`` does it for a whole run
and skips verdicts whose hypothesis it cannot find.
"""

from __future__ import annotations

import pytest

from autonomous_ai_agents.common.models import (
    ChangeClass,
    Hypothesis,
    HypothesisSource,
    Lesson,
    Verdict,
    VerdictOutcome,
    new_id,
)
from autonomous_ai_agents.learning import lessons as lessons_pkg
from autonomous_ai_agents.learning.lessons import (
    lesson_from_verdict,
    lessons_from_verdicts,
)
from autonomous_ai_agents.optimization.ranking import lesson_boost

PROJECT_ID = new_id()
TECHNIQUE_ID = new_id()


def _hypothesis(
    *,
    technique_id: str | None = TECHNIQUE_ID,
    title: str = "Cache CLIP embeddings to disk",
) -> Hypothesis:
    return Hypothesis(
        project_id=PROJECT_ID,
        source=HypothesisSource.playbook,
        technique_id=technique_id,
        title=title,
        rationale="Encoder is frozen; 42% of step time recomputes it.",
        change_class=ChangeClass.efficiency,
        expected_gain=0.4,
        provability=0.9,
        risk=0.1,
    )


def _verdict(
    hypothesis: Hypothesis,
    outcome: VerdictOutcome = VerdictOutcome.keep,
    *,
    gain: float | None = 0.417,
    hypothesis_id: str | None = None,
) -> Verdict:
    return Verdict(
        trial_id=new_id(),
        hypothesis_id=hypothesis_id or hypothesis.id,
        outcome=outcome,
        change_class=hypothesis.change_class,
        gain=gain,
        summary=f"{outcome.value}: summary",
    )


# ---------------------------------------------------------------------------
# lesson_from_verdict
# ---------------------------------------------------------------------------


def test_lesson_from_verdict_copies_ids_outcome_and_gain() -> None:
    """
    GIVEN a keep verdict for a playbook hypothesis
    WHEN a lesson is derived
    THEN it links verdict, hypothesis and technique and copies outcome and gain
    """
    hypothesis = _hypothesis()
    verdict = _verdict(hypothesis)

    lesson = lesson_from_verdict(verdict, hypothesis, project_id=PROJECT_ID)

    assert isinstance(lesson, Lesson)
    assert lesson.project_id == PROJECT_ID
    assert lesson.verdict_id == verdict.id
    assert lesson.hypothesis_id == hypothesis.id
    assert lesson.technique_id == TECHNIQUE_ID
    assert lesson.outcome is VerdictOutcome.keep
    assert lesson.gain == pytest.approx(0.417)
    assert lesson.weight == 1.0
    assert lesson.context == ()


def test_lesson_from_verdict_text_with_context_and_gain() -> None:
    """
    GIVEN context tags and a positive gain
    WHEN a lesson is derived
    THEN the text reads "<tags> -> <title>: <outcome> (+41.7%)"
    """
    hypothesis = _hypothesis()
    verdict = _verdict(hypothesis, gain=0.417)

    lesson = lesson_from_verdict(
        verdict,
        hypothesis,
        project_id=PROJECT_ID,
        context=("frozen_recompute", "python"),
    )

    assert lesson.context == ("frozen_recompute", "python")
    assert (
        lesson.text
        == "frozen_recompute, python -> Cache CLIP embeddings to disk: keep (+41.7%)"
    )


def test_lesson_from_verdict_text_without_gain_uses_general() -> None:
    """
    GIVEN no context and a verdict without a gain
    WHEN a lesson is derived
    THEN the text reads "general -> <title>: <outcome>" with no gain suffix
    """
    hypothesis = _hypothesis()
    verdict = _verdict(hypothesis, VerdictOutcome.reject, gain=None)

    lesson = lesson_from_verdict(verdict, hypothesis, project_id=PROJECT_ID)

    assert lesson.gain is None
    assert lesson.text == "general -> Cache CLIP embeddings to disk: reject"


def test_lesson_from_verdict_formats_negative_gain() -> None:
    """
    GIVEN a verdict whose gain is negative
    WHEN a lesson is derived
    THEN the suffix is "(-2.3%)"
    """
    hypothesis = _hypothesis(title="micro-tweak")
    verdict = _verdict(hypothesis, VerdictOutcome.inconclusive, gain=-0.023)

    lesson = lesson_from_verdict(verdict, hypothesis, project_id=PROJECT_ID)

    assert lesson.text == "general -> micro-tweak: inconclusive (-2.3%)"


def test_lesson_from_verdict_formats_zero_gain() -> None:
    """
    GIVEN a verdict whose gain is exactly 0
    WHEN a lesson is derived
    THEN the suffix is present and reads "(+0.0%)"
    """
    hypothesis = _hypothesis(title="no-op")
    verdict = _verdict(hypothesis, VerdictOutcome.inconclusive, gain=0.0)

    lesson = lesson_from_verdict(verdict, hypothesis, project_id=PROJECT_ID)

    assert lesson.text == "general -> no-op: inconclusive (+0.0%)"


def test_lesson_from_verdict_context_becomes_a_tuple() -> None:
    """
    GIVEN context given as a list
    WHEN a lesson is derived
    THEN it is stored as a tuple, order preserved
    """
    hypothesis = _hypothesis()
    verdict = _verdict(hypothesis)

    lesson = lesson_from_verdict(
        verdict, hypothesis, project_id=PROJECT_ID, context=["b", "a"]
    )

    assert lesson.context == ("b", "a")
    assert lesson.text.startswith("b, a -> ")


def test_lesson_from_verdict_without_project_is_global() -> None:
    """
    GIVEN project_id=None
    WHEN a lesson is derived
    THEN project_id is None (a global lesson)
    """
    hypothesis = _hypothesis()

    lesson = lesson_from_verdict(_verdict(hypothesis), hypothesis, project_id=None)

    assert lesson.project_id is None


def test_lesson_from_verdict_without_technique() -> None:
    """
    GIVEN a novel hypothesis with no technique
    WHEN a lesson is derived
    THEN technique_id is None but hypothesis_id still links it
    """
    hypothesis = _hypothesis(technique_id=None)

    lesson = lesson_from_verdict(_verdict(hypothesis), hypothesis, project_id=None)

    assert lesson.technique_id is None
    assert lesson.hypothesis_id == hypothesis.id


def test_lesson_from_verdict_rejects_mismatched_hypothesis() -> None:
    """
    GIVEN a verdict that belongs to a different hypothesis
    WHEN a lesson is derived
    THEN a ValueError is raised rather than mis-attributing the outcome
    """
    hypothesis = _hypothesis()
    verdict = _verdict(hypothesis, hypothesis_id=new_id())

    with pytest.raises(ValueError, match="hypothesis"):
        lesson_from_verdict(verdict, hypothesis, project_id=PROJECT_ID)


@pytest.mark.parametrize("outcome", list(VerdictOutcome))
def test_lesson_from_verdict_keeps_every_outcome(outcome: VerdictOutcome) -> None:
    """
    GIVEN a verdict with any outcome
    WHEN a lesson is derived
    THEN the outcome is copied verbatim and appears in the text
    """
    hypothesis = _hypothesis()

    lesson = lesson_from_verdict(
        _verdict(hypothesis, outcome, gain=None), hypothesis, project_id=None
    )

    assert lesson.outcome is outcome
    assert lesson.text.endswith(f": {outcome.value}")


def test_lesson_round_trips_through_json() -> None:
    """
    GIVEN a derived lesson
    WHEN dumped to JSON and validated back
    THEN it is unchanged (it will be checkpointed and stored as JSONB)
    """
    hypothesis = _hypothesis()
    lesson = lesson_from_verdict(
        _verdict(hypothesis), hypothesis, project_id=PROJECT_ID, context=("python",)
    )

    assert Lesson.model_validate_json(lesson.model_dump_json()) == lesson


# ---------------------------------------------------------------------------
# lessons_from_verdicts
# ---------------------------------------------------------------------------


def test_lessons_from_verdicts_builds_one_lesson_per_verdict_in_order() -> None:
    """
    GIVEN three verdicts whose hypotheses are all known
    WHEN lessons are derived
    THEN there is one lesson per verdict, in verdict order, sharing the context
    """
    h1, h2, h3 = (_hypothesis(title=f"h{i}") for i in range(3))
    verdicts = (
        _verdict(h1, VerdictOutcome.keep),
        _verdict(h2, VerdictOutcome.reject, gain=None),
        _verdict(h3, VerdictOutcome.needs_approval, gain=0.17),
    )

    lessons = lessons_from_verdicts(
        verdicts,
        {h.id: h for h in (h1, h2, h3)},
        project_id=PROJECT_ID,
        context=["python"],
    )

    assert isinstance(lessons, tuple)
    assert [lesson.verdict_id for lesson in lessons] == [v.id for v in verdicts]
    assert [lesson.outcome for lesson in lessons] == [v.outcome for v in verdicts]
    assert {lesson.context for lesson in lessons} == {("python",)}
    assert {lesson.project_id for lesson in lessons} == {PROJECT_ID}


def test_lessons_from_verdicts_skips_unknown_hypotheses() -> None:
    """
    GIVEN a verdict whose hypothesis is not in the mapping
    WHEN lessons are derived
    THEN that verdict is skipped and the others are kept
    """
    known = _hypothesis(title="known")
    orphan = _hypothesis(title="orphan")
    verdicts = (_verdict(orphan), _verdict(known), _verdict(orphan))

    lessons = lessons_from_verdicts(verdicts, {known.id: known}, project_id=PROJECT_ID)

    assert len(lessons) == 1
    assert lessons[0].hypothesis_id == known.id
    assert lessons[0].verdict_id == verdicts[1].id


def test_lessons_from_verdicts_with_no_verdicts() -> None:
    """
    GIVEN no verdicts
    WHEN lessons are derived
    THEN the result is an empty tuple
    """
    assert lessons_from_verdicts((), {}, project_id=PROJECT_ID) == ()
    assert lessons_from_verdicts([], {}, project_id=None) == ()


# ---------------------------------------------------------------------------
# Integration with ranking
# ---------------------------------------------------------------------------


def test_lessons_feed_the_next_ranking() -> None:
    """
    GIVEN a kept verdict and a rejected verdict for the same technique
    WHEN the derived lessons are fed to lesson_boost for a new hypothesis
    THEN they cancel out, and a lone keep boosts by 0.1
    """
    old_a = _hypothesis(title="old a")
    old_b = _hypothesis(title="old b")
    lessons = lessons_from_verdicts(
        (_verdict(old_a, VerdictOutcome.keep), _verdict(old_b, VerdictOutcome.reject)),
        {old_a.id: old_a, old_b.id: old_b},
        project_id=PROJECT_ID,
    )
    fresh = _hypothesis(title="fresh")

    assert lesson_boost(fresh, lessons) == pytest.approx(0.0)
    assert lesson_boost(fresh, lessons[:1]) == pytest.approx(0.1)


def test_learning_package_exports_nothing_yet() -> None:
    """
    GIVEN the learning package
    WHEN imported
    THEN its __all__ is empty (re-export only, so coverage can omit it)
    """
    import autonomous_ai_agents.learning as learning

    assert learning.__all__ == []
    assert lessons_pkg.__name__ == "autonomous_ai_agents.learning.lessons"
