"""Engine state: the TypedDict LangGraph checkpoints between nodes.

Two rules every node must follow:

- **Delta-only on reducer channels.** ``trials``, ``verdicts``, ``lessons``
  and ``events`` (see ``REDUCER_KEYS``) are ``Annotated[list, operator.add]``
  channels. LangGraph concatenates whatever a node returns for them onto the
  list already in state, so a node returns only the *new* items. Returning
  the full list duplicates every entry already there. Every other key is
  replaced wholesale by the node's return value.
- **Every key is always present.** LangGraph omits keys that were never set
  from the dict a node receives, so ``initial_state`` sets all of them and
  nodes index the state directly instead of using ``.get``.

``trials`` accumulates every *judged* trial of the run; ``round_trials`` is a
plain key holding the current round's trials (unjudged after ``trials``,
judged after ``judges``), so ``verdicts`` reads the judge results from the
checkpointed state and never from the repository.

``run_id`` names the checkpoint thread and the engine's git branches, so
``validate_run_id`` keeps it to a safe refname piece (``RUN_ID_PATTERN``).

``max_cost_usd`` is the run's hard cost cap; nodes that spend rebuild
``Budget(state["max_cost_usd"], state["cost_usd"])`` so the budget survives a
checkpoint and resume. ``budget_exhausted`` is set when the trials node stops
for lack of money, and the router then goes straight to combine.

``AgentState`` is a transitional alias for the placeholder nodes and tests
that still import the old name; it goes away with the node rewrite.
"""

import math
import operator
import re
from collections.abc import Sequence
from typing import Annotated, TypedDict

from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.models import (
    ApprovalDecision,
    Baseline,
    Combination,
    Delivery,
    EngineEvent,
    Guardrail,
    Hotspot,
    Hypothesis,
    Lesson,
    Objective,
    Paper,
    Project,
    ProjectUnderstanding,
    RunPhase,
    Technique,
    Trial,
    Verdict,
    Workload,
    new_id,
)

REDUCER_KEYS: frozenset[str] = frozenset({"trials", "verdicts", "lessons", "events"})
"""State keys with an ``operator.add`` reducer: nodes return deltas for these."""

RUN_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
"""A run id (and a hypothesis id): 1-64 refname-safe characters, alphanumeric first."""


def validate_run_id(run_id: str) -> str:
    """Return ``run_id`` when it can safely name a thread and a git branch piece.

    Beyond ``RUN_ID_PATTERN`` it must not contain ``..`` (git refuses it and
    it reads as traversal), end with ``.lock`` (git's lock files) or end with
    ``.`` (git refuses a refname ending in a dot). Raises ``ValueError``.
    """
    if (
        re.fullmatch(RUN_ID_PATTERN, run_id) is None
        or ".." in run_id
        or run_id.endswith((".lock", "."))
    ):
        raise ValueError(
            f"run_id {run_id!r} must be 1-64 letters, digits, '.', '_' or '-', "
            "start with a letter or digit, and contain no '..', '.lock' or "
            "trailing '.'"
        )
    return run_id


class EngineState(TypedDict):
    """Everything one engine run knows, checkpointed after every node."""

    run_id: str
    phase: RunPhase
    project: Project
    workloads: list[Workload]
    objectives: list[Objective]
    guardrails: list[Guardrail]
    round: int
    max_rounds: int
    baseline: Baseline | None
    hotspots: list[Hotspot]
    techniques: list[Technique]
    papers: list[Paper]
    hypotheses: list[Hypothesis]
    trials: Annotated[list[Trial], operator.add]
    round_trials: list[Trial]
    verdicts: Annotated[list[Verdict], operator.add]
    pending_approval_ids: list[str]
    approval: ApprovalDecision | None
    kept_verdict_ids: list[str]
    delivery: Delivery | None
    lessons: Annotated[list[Lesson], operator.add]
    events: Annotated[list[EngineEvent], operator.add]
    error: str | None
    tokens_used: int
    cost_usd: float
    base_commit: str | None
    understanding: ProjectUnderstanding | None
    max_cost_usd: float
    combination: Combination | None
    budget_exhausted: bool
    extra_protected: list[str]


AgentState = EngineState
"""Transitional alias; the placeholder nodes still import this name."""


def initial_state(
    project: Project,
    workloads: Sequence[Workload],
    objectives: Sequence[Objective],
    guardrails: Sequence[Guardrail],
    *,
    run_id: str | None = None,
    max_rounds: int | None = None,
    max_cost_usd: float | None = None,
) -> EngineState:
    """Build the state a run starts from, with every key set.

    The sequences are copied into fresh lists so later mutation by the caller
    cannot leak into a checkpoint. ``run_id`` defaults to a new uuid4 and is
    checked by ``validate_run_id``; ``max_rounds`` defaults to
    ``settings.MAX_TRIAL_ROUNDS`` and must be at least 1; ``max_cost_usd``
    defaults to ``settings.MAX_COST_USD`` and must be finite and at least 0.
    All three raise ``ValueError``.
    """
    rounds = max_rounds if max_rounds is not None else settings.MAX_TRIAL_ROUNDS
    if rounds < 1:
        raise ValueError(f"max_rounds must be at least 1, got {rounds}")
    cap = float(max_cost_usd if max_cost_usd is not None else settings.MAX_COST_USD)
    if not math.isfinite(cap) or cap < 0:
        raise ValueError(f"max_cost_usd must be finite and at least 0, got {cap}")
    return EngineState(
        run_id=validate_run_id(run_id if run_id is not None else new_id()),
        phase=RunPhase.connect,
        project=project,
        workloads=list(workloads),
        objectives=list(objectives),
        guardrails=list(guardrails),
        round=0,
        max_rounds=rounds,
        baseline=None,
        hotspots=[],
        techniques=[],
        papers=[],
        hypotheses=[],
        trials=[],
        round_trials=[],
        verdicts=[],
        pending_approval_ids=[],
        approval=None,
        kept_verdict_ids=[],
        delivery=None,
        lessons=[],
        events=[],
        error=None,
        tokens_used=0,
        cost_usd=0.0,
        base_commit=None,
        understanding=None,
        max_cost_usd=cap,
        combination=None,
        budget_exhausted=False,
        extra_protected=[],
    )
