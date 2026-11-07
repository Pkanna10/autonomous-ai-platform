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

Step 3 Wave 2 (D44, D65): ``generate`` also takes the run's facts as
keyword-only, defaulted parameters (the base commit, the run id, the index of
this generator call, the run's protected patterns and the editor's read-deny
paths), which today's adapter accepts and ignores; ``GenerateResult`` carries
typed ``events`` for the node to emit and the idea pipeline's ``stats``
(``None`` from today's generator), so the default path is unchanged.

Idea lab (G5b): ``generate`` also takes ``verdicts``, this run's verdicts so
far (``RunVerdicts``: each with its hypothesis and that hypothesis's
mechanism key, and the run's noise floor), keyword-only and ``None`` by
default. The idea pipeline builds its round seeds from them; today's
generator accepts and ignores them.
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
    Verdict,
    Workload,
)
from autonomous_ai_agents.optimization.idea_dedupe import IdeaKey
from autonomous_ai_agents.optimization.idea_types import GenerateEvent, IdeaStats


@dataclass(frozen=True)
class GenerateResult:
    """Validated hypotheses, the model's best first, and what was dropped;
    ``events`` the node emits with their codes and levels after ``generated``,
    ``stats`` what the idea pipeline counted (D65)."""

    hypotheses: tuple[Hypothesis, ...] = ()
    notes: tuple[str, ...] = ()
    events: tuple[GenerateEvent, ...] = ()
    stats: IdeaStats | None = None


@dataclass(frozen=True)
class Trialled:
    """One verdict of this run, the hypothesis it judged and that
    hypothesis's mechanism key as the pipeline recorded it (``None``: no key
    was recorded, e.g. a caller's candidate) (G5b). ``gain`` and ``floor`` are
    its deciding primary result's (``evolve.primary_gain_floor``), the floor
    counting the trial's own spread; ``None``: no measured primary result, and
    the seed falls back to ``Verdict.gain`` over the run's floor."""

    hypothesis: Hypothesis
    verdict: Verdict
    key: IdeaKey | None
    gain: float | None = None
    floor: float | None = None


@dataclass(frozen=True)
class RunVerdicts:
    """This run's verdicts so far, in their order, and the run's noise floor
    (the smallest provable relative gain; ``None``: not known) (G5b)."""

    trialled: tuple[Trialled, ...] = ()
    noise_floor: float | None = None


@dataclass(frozen=True)
class MatchResult:
    """Validated matches, best fit first, and what was dropped."""

    matches: tuple[TechniqueMatchRecord, ...] = ()
    notes: tuple[str, ...] = ()


@runtime_checkable
class HypothesisGenerator(Protocol):
    """Writes at most ``n`` obvious hypotheses plus the idea pipeline's
    portfolio (D53); ``lessons`` and ``avoid_titles`` are context for the
    prompt (ignored by today's generator until W1).

    The run's facts (D44): ``commit`` is the base commit the code is read at
    (``None``: no code context), ``run_id`` seeds the pipeline's rotation,
    ``call_index`` counts this run's earlier generator calls, ``protected``
    and ``read_deny`` are patterns and paths never to be shown, and
    ``workloads`` are the run's (the idea pipeline's input-shape view, G2)
    and ``verdicts`` this run's so far (the pipeline's round seeds, G5b).
    """

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
        commit: str | None = None,
        run_id: str | None = None,
        call_index: int = 0,
        protected: Sequence[str] = (),
        read_deny: Sequence[str] = (),
        workloads: Sequence[Workload] = (),
        verdicts: RunVerdicts | None = None,
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
