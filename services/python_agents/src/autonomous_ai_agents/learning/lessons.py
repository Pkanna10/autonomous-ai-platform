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
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence

from autonomous_ai_agents.common.models import Hypothesis, Lesson, Verdict

LESSON_NAMESPACE = uuid.UUID("6f1d3c2a-8e4b-5a7c-9d0e-1f2a3b4c5d6e")
"""uuid5 namespace for lesson ids: one verdict always teaches the same lesson id."""


def lesson_from_verdict(
    verdict: Verdict,
    hypothesis: Hypothesis,
    *,
    project_id: str | None,
    context: Sequence[str] = (),
    extra_context: Sequence[str] = (),
) -> Lesson:
    """Return the ``Lesson`` that ``verdict`` teaches about ``hypothesis``.

    ``project_id`` of ``None`` makes the lesson global. The text reads
    ``"<context tags or 'general'> -> <title>: <outcome> (<gain>)"``, the gain
    suffix present only when the verdict measured one; ``extra_context`` (the
    hypothesis's tags) joins ``context`` in the lesson's ``context`` only,
    deduplicated and sorted, and leaves it as given when empty. The id is the
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
    if verdict.gain is not None:
        text += f" ({verdict.gain:+.1%})"
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
        weight=1.0,
    )


def lessons_from_verdicts(
    verdicts: Sequence[Verdict],
    hypotheses_by_id: Mapping[str, Hypothesis],
    *,
    project_id: str | None,
    context: Sequence[str] = (),
) -> tuple[Lesson, ...]:
    """Return one lesson per verdict, in order, skipping unknown hypotheses;
    each lesson's context gains its hypothesis's tags (D57)."""
    lessons: list[Lesson] = []
    for verdict in verdicts:
        hypothesis = hypotheses_by_id.get(verdict.hypothesis_id)
        if hypothesis is None:
            continue
        lessons.append(
            lesson_from_verdict(
                verdict,
                hypothesis,
                project_id=project_id,
                context=context,
                extra_context=hypothesis.tags,
            )
        )
    return tuple(lessons)
