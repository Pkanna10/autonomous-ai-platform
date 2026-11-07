"""Tests for the lessons store helpers (Step 1, unit U3).

``lesson_from_verdict`` turns a verdict into the ``Lesson`` the next
hypothesis ranking reads; ``lessons_from_verdicts`` does it for a whole run
and skips verdicts whose hypothesis it cannot find.
"""

from __future__ import annotations

import uuid

import pytest

from autonomous_ai_agents.common.models import (
    ChangeClass,
    Combination,
    CombineSkip,
    Hypothesis,
    HypothesisSource,
    Lesson,
    Verdict,
    VerdictOutcome,
    new_id,
)
from autonomous_ai_agents.learning import lessons as lessons_pkg
from autonomous_ai_agents.learning.lessons import (
    COMBINE_HELD,
    COMBINE_NOT_REPRODUCED,
    COMBINE_SKIPPED,
    COMBINE_UNCONFIRMED,
    LESSON_NAMESPACE,
    CombineMark,
    combine_marks,
    lesson_from_verdict,
    lessons_from_verdicts,
)
from autonomous_ai_agents.optimization.idea_portfolio import lesson_titles
from autonomous_ai_agents.optimization.ranking import (
    lesson_boost,
    rank_generated,
    rank_hypotheses,
)
from autonomous_ai_agents.persistence.repository import InMemoryRepository

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


def test_lesson_id_is_derived_from_the_verdict_so_relearning_is_idempotent() -> None:
    """
    GIVEN one verdict learned twice (a re-executed learn node) and another verdict
    WHEN lessons are derived and both copies are saved to a repository
    THEN both copies share the uuid5 id of the verdict, the other verdict's
         lesson differs, and the repository holds a single row for the first
    """
    hypothesis = _hypothesis()
    verdict = _verdict(hypothesis)

    first = lesson_from_verdict(verdict, hypothesis, project_id=PROJECT_ID)
    again = lesson_from_verdict(
        verdict, hypothesis, project_id=PROJECT_ID, context=("python",)
    )
    other = lesson_from_verdict(_verdict(hypothesis), hypothesis, project_id=PROJECT_ID)

    assert first.id == again.id == str(uuid.uuid5(LESSON_NAMESPACE, verdict.id))
    assert uuid.UUID(first.id).version == 5
    assert other.id != first.id
    repository = InMemoryRepository()
    repository.save_lesson(first)
    repository.save_lesson(again)
    assert repository.list_lessons() == (again,)


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


# ---------------------------------------------------------------------------
# G11 (W2, D13; amends decision 25): a keep's weight follows its combine
# ---------------------------------------------------------------------------


def test_the_four_marks_are_the_w4_table() -> None:
    """The weights and tags of research-engine.md's Unit W4 table; only the
    two discounted rows add a note to the text."""
    table = {
        "combine:held": (1.0, None), "combine:skipped": (1.0, None),
        "combine:unconfirmed": (0.5, "combine: unconfirmed"),
        "combine:not_reproduced": (0.25, "combine: not reproduced"),
    }  # fmt: skip
    marks = (COMBINE_HELD, COMBINE_SKIPPED, COMBINE_UNCONFIRMED, COMBINE_NOT_REPRODUCED)
    assert {m.tag: (m.weight, m.note) for m in marks} == table
    with pytest.raises(ValueError):
        CombineMark(weight=0.0, tag="combine:held")
    with pytest.raises(ValueError):
        CombineMark(weight=1.5, tag="combine:held")


def test_a_weight_and_a_note_change_the_lesson_never_its_outcome() -> None:
    """
    GIVEN a keep verdict with a gain
    WHEN its lesson is derived with weight 0.25 and the not-reproduced note
    THEN the outcome and gain are the verdict's, the weight is 0.25 and the
         note joins the gain's parenthesis, so ``lesson_titles`` (S4a's lesson
         filter) still reads the title; without a gain the note stands alone
    """
    hypothesis = _hypothesis(title="Cache: the parsed tokens")
    verdict = _verdict(hypothesis)
    plain = lesson_from_verdict(verdict, hypothesis, project_id=PROJECT_ID)
    noted = lesson_from_verdict(verdict, hypothesis, project_id=PROJECT_ID,
                                weight=0.25, note="combine: not reproduced")  # fmt: skip
    assert plain.weight == 1.0 and plain.text.endswith("keep (+41.7%)")
    assert (noted.outcome, noted.gain, noted.weight) == (
        VerdictOutcome.keep,
        0.417,
        0.25,
    )
    assert noted.text == (
        "general -> Cache: the parsed tokens: keep (+41.7%; combine: not reproduced)"
    )
    assert noted.id == plain.id
    bare = lesson_from_verdict(_verdict(hypothesis, gain=None), hypothesis,
                               project_id=PROJECT_ID, note="combine: unconfirmed")  # fmt: skip
    assert bare.text.endswith(": keep (combine: unconfirmed)")
    assert lesson_titles([noted, bare]) == {"Cache: the parsed tokens"}


def _combination(
    *,
    applied: tuple[str, ...] = (),
    skipped: tuple[CombineSkip, ...] = (),
    holds: bool,
    fallback: str | None = None,
) -> Combination:
    return Combination(
        base_commit="a" * 40, tip_commit="b" * 40, applied_trial_ids=applied,
        skipped=skipped, holds=holds, fallback_trial_id=fallback, summary="s",
    )  # fmt: skip


def _offered(*names: str) -> dict[str, Verdict]:
    return {
        name: Verdict(id=f"v-{name}", trial_id=f"t-{name}", hypothesis_id=f"h-{name}",
                      outcome=VerdictOutcome.keep, change_class=ChangeClass.efficiency,
                      gain=0.2, summary="keep")
        for name in names
    }  # fmt: skip


def _marks(
    offered: dict[str, Verdict], combination: Combination | None, kept: tuple[str, ...]
) -> dict[str, str | None]:
    found = combine_marks(list(offered.values()), combination,
                          [offered[k].id for k in kept])  # fmt: skip
    return {
        name: None if (m := found.get(v.id)) is None else m.tag
        for name, v in offered.items()
    }


def test_held_and_skipped_count_in_full() -> None:
    """
    GIVEN a greedy re-test that held over a and b, c skipped for a conflict
          and d for nothing left
    THEN a and b are held, c and d skipped, every one at weight 1.0
    """
    offered = _offered("a", "b", "c", "d")
    skips = (CombineSkip(trial_id="t-c", reason="conflict", paths=("x.py",)),
             CombineSkip(trial_id="t-d", reason="nothing left to apply"))  # fmt: skip
    combination = _combination(applied=("t-a", "t-b"), skipped=skips, holds=True)
    assert _marks(offered, combination, ("a", "b")) == {
        "a": "combine:held", "b": "combine:held",
        "c": "combine:skipped", "d": "combine:skipped",
    }  # fmt: skip
    found = combine_marks(list(offered.values()), combination, ["v-a", "v-b"])
    assert {m.weight for m in found.values()} == {1.0}


def test_a_keep_applied_in_a_failed_greedy_re_test_is_unconfirmed_when_a_fallback_held() -> (
    None
):
    """
    GIVEN a greedy re-test over a and b that failed, then b's fallback held
    THEN b is held; a, applied in the failed re-test (not kept, not
         skipped: the record keeps only the final application), unconfirmed
    """
    offered = _offered("a", "b")
    combination = _combination(applied=("t-b",), holds=True, fallback="t-b")
    assert _marks(offered, combination, ("b",)) == {
        "a": "combine:unconfirmed", "b": "combine:held",
    }  # fmt: skip


def test_no_fallback_held_means_not_reproduced() -> None:
    """
    GIVEN a failed greedy re-test over a and b whose fallback b failed too;
          and, alone, a single change whose re-test failed with no fallback
          (the sortedcontainers case)
    THEN a (in the failed re-test) and b (its own fallback failed) are not
         reproduced, and so is the lone change
    """
    offered = _offered("a", "b")
    both = _combination(applied=("t-b",), holds=False, fallback="t-b")
    assert _marks(offered, both, ()) == {
        "a": "combine:not_reproduced", "b": "combine:not_reproduced",
    }  # fmt: skip
    lone = _offered("s")
    assert _marks(lone, _combination(applied=("t-s",), holds=False), ()) == {
        "s": "combine:not_reproduced"
    }


def test_a_skipped_change_re_tested_as_the_fallback_is_judged_by_that_re_test() -> None:
    """
    GIVEN a applied, b skipped for a conflict; the re-test failed and b was
          the fallback: once it held, once it failed, once it was skipped
          again (never measured)
    THEN held, not reproduced, and skipped (a then not reproduced, since
         no fallback held)
    """
    offered = _offered("a", "b")
    conflict = CombineSkip(trial_id="t-b", reason="conflict")
    held = _combination(
        applied=("t-b",), skipped=(conflict,), holds=True, fallback="t-b"
    )
    failed = _combination(applied=("t-b",), skipped=(conflict,), holds=False,
                          fallback="t-b")  # fmt: skip
    again = _combination(skipped=(conflict, conflict), holds=False, fallback="t-b")
    assert _marks(offered, held, ("b",)) == {"a": "combine:unconfirmed",
                                              "b": "combine:held"}  # fmt: skip
    assert _marks(offered, failed, ())["b"] == "combine:not_reproduced"
    assert _marks(offered, again, ()) == {"a": "combine:not_reproduced",
                                           "b": "combine:skipped"}  # fmt: skip


def test_no_combiner_marks_nothing() -> None:
    offered = _offered("a")
    assert combine_marks(list(offered.values()), None, ["v-a"]) == {}


def test_lessons_from_verdicts_carries_each_mark() -> None:
    """
    GIVEN two keeps marked held and not reproduced, and an unmarked reject
    WHEN the run's lessons are derived
    THEN each keep has its weight, its tag in the context (never in the
         text's tag list) and the note in the text; the reject has weight
         1.0 and no tag; the ids are the verdicts' uuid5 as before
    """
    kept, lost, bad = (
        _hypothesis(title=t) for t in ("kept one", "lost one", "bad one")
    )
    verdicts = (_verdict(kept), _verdict(lost), _verdict(bad, VerdictOutcome.reject))
    marks = {verdicts[0].id: COMBINE_HELD, verdicts[1].id: COMBINE_NOT_REPRODUCED}
    lessons = lessons_from_verdicts(
        verdicts, {h.id: h for h in (kept, lost, bad)}, project_id=PROJECT_ID,
        context=("hot_loop",), marks=marks,
    )  # fmt: skip
    assert [lesson.weight for lesson in lessons] == [1.0, 0.25, 1.0]
    assert [lesson.context for lesson in lessons] == [
        ("combine:held", "hot_loop"), ("combine:not_reproduced", "hot_loop"),
        ("hot_loop",),
    ]  # fmt: skip
    assert lessons[0].text == "hot_loop -> kept one: keep (+41.7%)"
    assert lessons[1].text == (
        "hot_loop -> lost one: keep (+41.7%; combine: not reproduced)"
    )
    assert [lesson.id for lesson in lessons] == [
        str(uuid.uuid5(LESSON_NAMESPACE, v.id)) for v in verdicts
    ]
    again = lessons_from_verdicts(verdicts, {h.id: h for h in (kept, lost, bad)},
                                  project_id=PROJECT_ID, context=("hot_loop",),
                                  marks=marks)  # fmt: skip
    assert [lesson.model_dump(exclude={"created_at"}) for lesson in again] == [
        lesson.model_dump(exclude={"created_at"}) for lesson in lessons
    ]


def test_a_not_reproduced_keep_no_longer_outranks_a_held_one() -> None:
    """
    GIVEN technique t1 with two keeps that were not reproduced and t2 with
          one keep that held, and two equal-merit ideas, t1's first
    THEN unweighted (Step 2) t1 ranks first (0.2 against 0.1); weighted,
         t2 does (0.1 against 0.05), in ``rank_hypotheses`` and in
         ``rank_generated`` at equal position weight
    """
    old = [_hypothesis(technique_id="t1", title=f"t1 old {i}") for i in range(2)]
    old.append(_hypothesis(technique_id="t2", title="t2 old"))
    verdicts = [_verdict(h) for h in old]
    known = {h.id: h for h in old}
    marks = {verdicts[0].id: COMBINE_NOT_REPRODUCED,
             verdicts[1].id: COMBINE_NOT_REPRODUCED, verdicts[2].id: COMBINE_HELD}  # fmt: skip
    unweighted = lessons_from_verdicts(verdicts, known, project_id=PROJECT_ID)
    weighted = lessons_from_verdicts(verdicts, known, project_id=PROJECT_ID,
                                     marks=marks)  # fmt: skip
    first = _hypothesis(technique_id="t1", title="t1 new")
    second = _hypothesis(technique_id="t2", title="t2 new")
    assert [h.title for h in rank_hypotheses([first, second], unweighted)] == [
        "t1 new", "t2 new",
    ]  # fmt: skip
    assert [h.title for h in rank_hypotheses([first, second], weighted)] == [
        "t2 new", "t1 new",
    ]  # fmt: skip
    assert lesson_boost(first, weighted) == pytest.approx(0.05)
    assert lesson_boost(second, weighted) == pytest.approx(0.1)
    one = rank_generated([first], weighted)[0].score
    two = rank_generated([second], weighted)[0].score
    assert two > one


def test_learning_package_exports_nothing_yet() -> None:
    """
    GIVEN the learning package
    WHEN imported
    THEN its __all__ is empty (re-export only, so coverage can omit it)
    """
    import autonomous_ai_agents.learning as learning

    assert learning.__all__ == []
    assert lessons_pkg.__name__ == "autonomous_ai_agents.learning.lessons"
