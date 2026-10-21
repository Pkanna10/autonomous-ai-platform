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

``AgentState`` is a transitional alias for the placeholder nodes and tests
that still import the old name; it goes away with the node rewrite.
"""

import operator
from collections.abc import Sequence
from typing import Annotated, TypedDict

from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.models import (
    ApprovalDecision,
    Baseline,
    Delivery,
    EngineEvent,
    Guardrail,
    Hotspot,
    Hypothesis,
    Lesson,
    Objective,
    Paper,
    Project,
    RunPhase,
    Technique,
    Trial,
    Verdict,
    Workload,
    new_id,
)

REDUCER_KEYS: frozenset[str] = frozenset({"trials", "verdicts", "lessons", "events"})
"""State keys with an ``operator.add`` reducer: nodes return deltas for these."""


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
) -> EngineState:
    """Build the state a run starts from, with every key set.

    The sequences are copied into fresh lists so later mutation by the caller
    cannot leak into a checkpoint. ``run_id`` defaults to a new uuid4 and
    ``max_rounds`` to ``settings.MAX_TRIAL_ROUNDS``.
    """
    return EngineState(
        run_id=run_id if run_id is not None else new_id(),
        phase=RunPhase.connect,
        project=project,
        workloads=list(workloads),
        objectives=list(objectives),
        guardrails=list(guardrails),
        round=0,
        max_rounds=max_rounds if max_rounds is not None else settings.MAX_TRIAL_ROUNDS,
        baseline=None,
        hotspots=[],
        techniques=[],
        papers=[],
        hypotheses=[],
        trials=[],
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
    )
