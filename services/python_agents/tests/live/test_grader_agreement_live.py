"""Live L3: does the sweep's Opus 4.8 grader agree with hand labels?

The labels (``tests/fixtures/grader_labels.json``) are ground truth the Lead
owns: each pairs one idea (title and rationale, as a generated hypothesis
carries them) with a corpus repository's reference fix, read from its
``_solutions`` dir (``discovery_grader.reference_patches``), and says whether
the idea targets a reference root cause (``hit``, with the part it targets)
or not (``miss``). Near misses touch the hot code or its module but leave the
root cause in place; they are what an over-generous grader would count.

One grader request per repository, exactly as the sweep grades an arm
(``discovery_grader.grade``: the fix, then that repository's ideas shuffled
and scrubbed, never a label), so the run's cap is one ``GRADE_WORST_USD``
per repository, rounded up (``agreement_cap``; at most ``MAX_REQUESTS``, the
spec's 10 x ``GRADE_WORST_USD``). It feeds whether L4's hit@k counts.

Asserted: every request answered and billed only the grader's model; at
least 9 of every 10 labels agree (a ``hit`` on a ``multi`` repository also
names the labelled part; an ungraded idea disagrees); no near miss is graded
a hit. Each label's verdict and the totals go to the cost table's notes.
``test_grader_guards.py`` checks all of it offline.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, Self

import pytest
from pydantic import BaseModel, ConfigDict, Field, model_validator

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.common.models import ChangeClass, Hypothesis, HypothesisSource

from .conftest import TESTS_DIR, LiveRun, StartLive
from .corpus import CORPUS, HARD_CORPUS, CorpusRepo
from .discovery import ceil_usd
from .discovery_grader import (
    GRADE_WORST_USD,
    GRADER_MODEL,
    Grade,
    ReferencePatch,
    grade,
    reference_patches,
    scrub,
)
from .discovery_sweep import SWEEP_N

pytestmark = pytest.mark.live

LABELS_PATH: Final = TESTS_DIR / "fixtures" / "grader_labels.json"
MAX_REQUESTS: Final = 10  # L3's cap: 10 x GRADE_WORST_USD
MIN_AGREEMENT: Final = (9, 10)  # at least 9 of every 10 labels agree
__all__ = ["GRADER_MODEL", "LABELS_PATH", "MAX_REQUESTS", "MIN_AGREEMENT"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class GraderLabel(_Frozen):
    """One idea, the repository whose reference fix it is graded against,
    and the true answer with a one-line reason (never shown to the grader)."""

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    repo: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=120)
    rationale: str = Field(min_length=1, max_length=600)
    label: Literal["hit", "miss"]
    part: int | None = Field(ge=1)  # a hit: the reference part it targets
    near_miss: bool
    why: str = Field(min_length=1, max_length=400)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.label == "hit" and (self.part is None or self.near_miss):
            raise ValueError(f"{self.id}: a hit names its part and is no near miss")
        if self.label == "miss" and self.part is not None:
            raise ValueError(f"{self.id}: a miss targets no part")
        if scrub(self.title + self.rationale) != self.title + self.rationale:
            raise ValueError(f"{self.id}: names a model the grader would not see")
        return self


class GraderLabels(_Frozen):
    source: str = Field(min_length=1, max_length=600)
    labels: tuple[GraderLabel, ...] = Field(min_length=10, max_length=12)

    @model_validator(mode="after")
    def _distinct(self) -> Self:
        ids, titles = set(), set()
        for label in self.labels:
            title = (label.repo, " ".join(label.title.split()).casefold())
            if label.id in ids:
                raise ValueError(f"{label.id}: the file repeats an id")
            if title in titles:
                raise ValueError(f"{label.id}: the file repeats a title")
            ids.add(label.id)
            titles.add(title)
        return self


@dataclass(frozen=True)
class LabelGroup:
    """One repository's labels: one grader request."""

    repo: CorpusRepo
    patches: tuple[ReferencePatch, ...]
    labels: tuple[GraderLabel, ...]

    def hypotheses(self) -> tuple[Hypothesis, ...]:
        """The labels as the generator's hypotheses (the grader reads only
        the title and the rationale)."""
        return tuple(
            Hypothesis(
                project_id=f"grader-labels-{self.repo.name}",
                source=HypothesisSource.novel,
                title=label.title,
                rationale=label.rationale,
                change_class=ChangeClass.efficiency,
                expected_gain=0.5,
                provability=0.5,
                risk=0.1,
            )
            for label in self.labels
        )


_REPOS: Final = {repo.name: repo for repo in (*CORPUS, *HARD_CORPUS)}


def label_groups(
    labels: GraderLabels,
    repos: Mapping[str, CorpusRepo] = _REPOS,
    max_requests: int = MAX_REQUESTS,
) -> tuple[LabelGroup, ...]:
    """One group per repository, in first-label order. A repository must be
    a corpus one with a reference fix, hold at most ``SWEEP_N`` labels (the
    grader's prompt bound) and name only parts its fix has."""
    groups: list[LabelGroup] = []
    for name in dict.fromkeys(label.repo for label in labels.labels):
        repo = repos.get(name)
        if repo is None or repo.kind == "control":
            raise ValueError(f"{name}: not a graded corpus repository")
        mine = tuple(label for label in labels.labels if label.repo == name)
        if len(mine) > SWEEP_N:
            raise ValueError(f"{name}: more than {SWEEP_N} labels for one request")
        patches = reference_patches(repo)
        for label in mine:
            if label.part is not None and label.part > len(patches):
                raise ValueError(
                    f"{label.id}: targets part {label.part} of {len(patches)}"
                )
        groups.append(LabelGroup(repo, patches, mine))
    if len(groups) > max_requests:
        raise ValueError(f"more than {max_requests} repositories (one request each)")
    return tuple(groups)


def load_groups(path: Path = LABELS_PATH) -> tuple[LabelGroup, ...]:
    """The label file, validated, as one group per repository."""
    text = path.read_text(encoding="utf-8")
    return label_groups(GraderLabels.model_validate_json(text))


def agreement_cap(groups: Sequence[LabelGroup]) -> float:
    """One worst-case grader request per repository, rounded up."""
    return ceil_usd(len(groups) * GRADE_WORST_USD)


@dataclass(frozen=True)
class Verdict:
    """One label and what the grader said (``None``: ungraded)."""

    label: GraderLabel
    hit: bool | None
    part: int | None
    parts: int  # how many reference parts the grader was shown

    @property
    def agrees(self) -> bool:
        if self.label.label == "miss":
            return self.hit is False
        return self.hit is True and (self.parts == 1 or self.part == self.label.part)

    def note(self) -> str:
        said = "ungraded" if self.hit is None else ("hit" if self.hit else "miss")
        part = "" if self.part is None else f" part {self.part}"
        truth = self.label.label + (
            "" if self.label.part is None else f" part {self.label.part}"
        )
        near = " (near miss)" if self.label.near_miss else ""
        mark = "agrees" if self.agrees else "DISAGREES"
        return f"{self.label.id}: label {truth}{near}, grader {said}{part}: {mark}"


def verdicts_of(group: LabelGroup, graded: Grade) -> tuple[Verdict, ...]:
    """``graded`` (in the labels' order) against ``group``'s labels."""
    causes = graded.causes or (None,) * len(graded.hits)
    return tuple(
        Verdict(label, hit, cause, graded.parts)
        for label, hit, cause in zip(group.labels, graded.hits, causes, strict=True)
    )


@dataclass(frozen=True)
class Agreement:
    verdicts: tuple[Verdict, ...]
    grades: tuple[tuple[LabelGroup, Grade], ...]

    @property
    def agreed(self) -> int:
        return sum(verdict.agrees for verdict in self.verdicts)

    @property
    def near_miss_false_positives(self) -> tuple[Verdict, ...]:
        return tuple(v for v in self.verdicts if v.label.near_miss and v.hit is True)

    def notes(self) -> list[str]:
        """One line per label, then the totals (no model text: the grader's
        justifications stay out of the job summary)."""
        total = (
            f"L3 agreement {self.agreed}/{len(self.verdicts)}, "
            f"near-miss hits {len(self.near_miss_false_positives)}"
        )
        return [verdict.note() for verdict in self.verdicts] + [total]


def grade_labels(run: LiveRun, groups: Sequence[LabelGroup]) -> Agreement:
    """One grader request per group on ``run``'s budget."""
    budget = Budget(run.cap_usd, run.spent_usd)
    grades: list[tuple[LabelGroup, Grade]] = []
    verdicts: list[Verdict] = []
    for group in groups:
        graded = grade(run, budget, group.repo, group.patches, group.hypotheses())
        grades.append((group, graded))
        verdicts += verdicts_of(group, graded)
    return Agreement(tuple(verdicts), tuple(grades))


def check_agreement(result: Agreement) -> None:
    """Every request answered on the grader's model alone; at least
    ``MIN_AGREEMENT``; no near miss graded a hit."""
    for group, graded in result.grades:
        name = group.repo.name
        assert graded.answered and graded.error is None, (
            f"the grader failed on {name}: {graded.error}"
        )
        assert graded.models == (GRADER_MODEL,), f"{name} billed {graded.models}"
    wrong = ", ".join(v.label.id for v in result.near_miss_false_positives)
    assert not wrong, f"a near miss graded a hit: {wrong}"
    agreed, total = result.agreed, len(result.verdicts)
    low, high = MIN_AGREEMENT
    assert agreed * high >= low * total, (
        f"agreement {agreed}/{total} is below {low}/{high}: "
        + ", ".join(v.label.id for v in result.verdicts if not v.agrees)
    )


def test_grader_agrees_with_the_hand_labels(live: StartLive) -> None:
    groups = load_groups()  # read and checked before any spend
    run = live(agreement_cap(groups))
    result = grade_labels(run, groups)
    for line in result.notes():
        run.note(line)
    check_agreement(result)
