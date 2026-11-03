"""Lessons: what each verdict teaches the engine for the next run.

Pure functions, no I/O. A ``Lesson`` records the outcome (and gain) of one
verdict against the technique and hypothesis it judged, with context tags
describing when it applies. ``optimization.ranking.lesson_boost`` reads them
back when ranking the next round's hypotheses.

Step 3 Wave 2 (D57): a hypothesis's ``tags`` (its lane, review verdict and
the model's ``claimed_`` labels) join the lesson's ``context``, deduplicated
and sorted, so they are queryable later; the ``text`` keeps being built from
the node's context only, so the text later shown to a model never gains the
claimed labels. Nothing reads the tags yet.

Step 3 idea lab (G11, W2, D13; amends decision 25): a keep's lesson weighs
what the combine did with it (``combine_marks``, research-engine.md's Unit
W4 table): held or skipped 1.0, applied in a failed greedy re-test while
another fallback held 0.5 (``combine:unconfirmed``), not reproduced 0.25
(``combine:not_reproduced``), no combiner 1.0 with no tag. The tag joins the
context; the two discounted rows add a note to the text, inside the gain's
parenthesis (``"keep (+12.0%; combine: not reproduced)"``) so the title
still parses (``idea_portfolio.lesson_titles``). The outcome stays the
verdict's: only how much a keep counts in the next ranking changes.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Mapping, Sequence

from pydantic import Field

from autonomous_ai_agents.common.models import (
    Combination,
    EngineModel,
    Hypothesis,
    Lesson,
    Verdict,
)

LESSON_NAMESPACE = uuid.UUID("6f1d3c2a-8e4b-5a7c-9d0e-1f2a3b4c5d6e")
"""uuid5 namespace for lesson ids: one verdict always teaches the same lesson id."""


class CombineMark(EngineModel):
    """What the combine did with one kept change: its lesson's weight, the
    tag its context gains and the note its text gains (W2)."""

    weight: float = Field(gt=0, le=1)
    tag: str
    note: str | None = None


COMBINE_HELD = CombineMark(weight=1.0, tag="combine:held")
COMBINE_SKIPPED = CombineMark(weight=1.0, tag="combine:skipped")
COMBINE_UNCONFIRMED = CombineMark(
    weight=0.5, tag="combine:unconfirmed", note="combine: unconfirmed"
)
COMBINE_NOT_REPRODUCED = CombineMark(
    weight=0.25, tag="combine:not_reproduced", note="combine: not reproduced"
)


def combine_marks(
    offered: Sequence[Verdict],
    combination: Combination | None,
    kept_verdict_ids: Collection[str],
) -> dict[str, CombineMark]:
    """The mark of each verdict ``offered`` to ``combination`` (the run set),
    by verdict id; empty with no combination (no combiner, or nothing kept).

    In order: delivered (in ``kept_verdict_ids``) is held; the fallback that
    was applied and did not hold is not reproduced; one recorded skipped and
    not applied in the final re-test is skipped; any other was applied in
    the failed greedy re-test: unconfirmed when a fallback held, else not
    reproduced. ``Combination`` keeps only the final re-test's applied ids,
    so that last row is inferred (offered, not skipped, not delivered); a
    combiner that dropped a change from both lists reads the same way.
    """
    if combination is None:
        return {}
    kept, applied = set(kept_verdict_ids), set(combination.applied_trial_ids)
    skipped = {skip.trial_id for skip in combination.skipped}
    marks: dict[str, CombineMark] = {}
    for verdict in offered:
        trial = verdict.trial_id
        if verdict.id in kept:
            mark = COMBINE_HELD
        elif trial == combination.fallback_trial_id and trial in applied:
            mark = COMBINE_NOT_REPRODUCED  # its own fallback failed
        elif trial in skipped and trial not in applied:
            mark = COMBINE_SKIPPED
        elif combination.holds:
            mark = COMBINE_UNCONFIRMED
        else:
            mark = COMBINE_NOT_REPRODUCED
        marks[verdict.id] = mark
    return marks


def lesson_from_verdict(
    verdict: Verdict,
    hypothesis: Hypothesis,
    *,
    project_id: str | None,
    context: Sequence[str] = (),
    extra_context: Sequence[str] = (),
    weight: float = 1.0,
    note: str | None = None,
) -> Lesson:
    """Return the ``Lesson`` that ``verdict`` teaches about ``hypothesis``.

    ``project_id`` of ``None`` makes the lesson global. The text reads
    ``"<context tags or 'general'> -> <title>: <outcome> (<gain>)"``, the gain
    suffix present only when the verdict measured one; ``extra_context`` (the
    hypothesis's tags) joins ``context`` in the lesson's ``context`` only,
    deduplicated and sorted, and leaves it as given when empty. ``weight``
    is the lesson's (W2); ``note`` joins the gain's parenthesis, or stands
    in one of its own when no gain was measured. The id is the
    uuid5 of the verdict id, so learning the same verdict twice (a re-executed
    learn node) replaces the stored lesson instead of adding a second one.

    Raises ``ValueError`` when the verdict belongs to a different hypothesis,
    so an outcome is never attributed to the wrong idea.
    """
    if verdict.hypothesis_id != hypothesis.id:
        raise ValueError(
            f"verdict {verdict.id} is about hypothesis {verdict.hypothesis_id}, "
            f"not {hypothesis.id}"
        )
    tags = tuple(context)
    text = (
        f"{', '.join(tags) or 'general'} -> {hypothesis.title}: {verdict.outcome.value}"
    )
    suffix = [] if verdict.gain is None else [f"{verdict.gain:+.1%}"]
    if note is not None:
        suffix.append(note)
    if suffix:
        text += f" ({'; '.join(suffix)})"
    if extra_context:
        tags = tuple(sorted({*tags, *extra_context}))
    return Lesson(
        id=str(uuid.uuid5(LESSON_NAMESPACE, verdict.id)),
        project_id=project_id,
        verdict_id=verdict.id,
        hypothesis_id=hypothesis.id,
        technique_id=hypothesis.technique_id,
        context=tags,
        outcome=verdict.outcome,
        gain=verdict.gain,
        text=text,
        weight=weight,
    )


def lessons_from_verdicts(
    verdicts: Sequence[Verdict],
    hypotheses_by_id: Mapping[str, Hypothesis],
    *,
    project_id: str | None,
    context: Sequence[str] = (),
    marks: Mapping[str, CombineMark] | None = None,
) -> tuple[Lesson, ...]:
    """Return one lesson per verdict, in order, skipping unknown hypotheses;
    each lesson's context gains its hypothesis's tags (D57) and, when
    ``marks`` holds the verdict's id, its combine mark (W2)."""
    lessons: list[Lesson] = []
    for verdict in verdicts:
        hypothesis = hypotheses_by_id.get(verdict.hypothesis_id)
        if hypothesis is None:
            continue
        mark = None if marks is None else marks.get(verdict.id)
        extra = hypothesis.tags if mark is None else (*hypothesis.tags, mark.tag)
        lessons.append(
            lesson_from_verdict(
                verdict,
                hypothesis,
                project_id=project_id,
                context=context,
                extra_context=extra,
                weight=1.0 if mark is None else mark.weight,
                note=None if mark is None else mark.note,
            )
        )
    return tuple(lessons)
