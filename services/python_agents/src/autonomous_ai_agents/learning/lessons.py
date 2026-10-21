"""Lessons: what each verdict teaches the engine for the next run.

Pure functions, no I/O. A ``Lesson`` records the outcome (and gain) of one
verdict against the technique and hypothesis it judged, with context tags
describing when it applies. ``optimization.ranking.lesson_boost`` reads them
back when ranking the next round's hypotheses.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from autonomous_ai_agents.common.models import Hypothesis, Lesson, Verdict


def lesson_from_verdict(
    verdict: Verdict,
    hypothesis: Hypothesis,
    *,
    project_id: str | None,
    context: Sequence[str] = (),
) -> Lesson:
    """Return the ``Lesson`` that ``verdict`` teaches about ``hypothesis``.

    ``project_id`` of ``None`` makes the lesson global. The text reads
    ``"<context tags or 'general'> -> <title>: <outcome> (<gain>)"``, the gain
    suffix present only when the verdict measured one.

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
    return Lesson(
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
    """Return one lesson per verdict, in order, skipping unknown hypotheses."""
    lessons: list[Lesson] = []
    for verdict in verdicts:
        hypothesis = hypotheses_by_id.get(verdict.hypothesis_id)
        if hypothesis is None:
            continue
        lessons.append(
            lesson_from_verdict(
                verdict, hypothesis, project_id=project_id, context=context
            )
        )
    return tuple(lessons)
