"""Discovery seams (Step 3, L4 and L6): who proposes hypotheses, who matches.

``HypothesisGenerator`` writes new hypotheses for the hypotheses node;
``TechniqueMatcher`` picks playbook techniques for the research node in
``matched`` mode. Both spend through the ``Budget`` they are handed, so the
node reads their spend from the budget's delta, never from the result. The
Claude-backed implementations live in ``optimization/hypothesis_source.py``
(U7); a ``NodeContext`` field of ``None`` keeps the Step 2 behaviour.

Results are frozen dataclasses: they cross one call. What reaches the state
is the engine models they carry (``Hypothesis``, ``TechniqueMatchRecord``).
``HypothesisSource`` (``common/models.py``) is the unrelated enum of origins.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.common.models import (
    Hotspot,
    Hypothesis,
    Lesson,
    Objective,
    Project,
    ProjectUnderstanding,
    Technique,
    TechniqueMatchRecord,
)


@dataclass(frozen=True)
class GenerateResult:
    """Validated hypotheses, the model's best first, and what was dropped."""

    hypotheses: tuple[Hypothesis, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class MatchResult:
    """Validated matches, best fit first, and what was dropped."""

    matches: tuple[TechniqueMatchRecord, ...] = ()
    notes: tuple[str, ...] = ()


@runtime_checkable
class HypothesisGenerator(Protocol):
    """Writes at most ``n`` hypotheses; ``lessons`` and ``avoid_titles`` are
    context for the prompt (ignored until W1)."""

    def generate(
        self,
        *,
        project: Project,
        understanding: ProjectUnderstanding | None,
        hotspots: Sequence[Hotspot],
        objective: Objective,
        techniques: Sequence[Technique],
        lessons: Sequence[Lesson],
        avoid_titles: Sequence[str],
        n: int,
        budget: Budget,
    ) -> GenerateResult: ...


@runtime_checkable
class TechniqueMatcher(Protocol):
    """Picks at most ``k`` of ``techniques`` that fit the project."""

    def match(
        self,
        *,
        understanding: ProjectUnderstanding | None,
        hotspots: Sequence[Hotspot],
        techniques: Sequence[Technique],
        k: int,
        budget: Budget,
    ) -> MatchResult: ...
