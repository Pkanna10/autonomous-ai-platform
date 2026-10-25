"""Claude-backed discovery adapters (Step 3, U7): the U2 seams over the Step 2 code.

``ClaudeHypothesisGenerator`` implements ``HypothesisGenerator`` over
``optimization.generate.generate_hypotheses``; ``ClaudeTechniqueMatcher``
implements ``TechniqueMatcher`` over ``research.playbook.match_techniques``
and returns the state's ``TechniqueMatchRecord``. Each adapter is built with
its role's transport (``common.config.role_settings``): construction refuses
a transport whose chain is not ``role_chain(config, role)`` (new roles run
alone, no fallbacks, D5) or an effort that chain rejects, so a wiring error
fails before any spend.

Every request is billed to the ``Budget`` handed in; the result carries no
cost, so the node reads spend from the budget's delta (D7). ``BudgetExceeded``
(before sending), ``LLMConfigError``, ``LLMRequestError``, ``LLMUnavailable``
and ``UnusableReplyError`` (after charging) propagate: which of them are soft
is the node's decision (D18, spec 4.1). ``lessons`` and ``avoid_titles`` are
accepted and ignored until W1 (D21). The hypothesis text stays untrusted: the
editor fences it for every source (D11).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.structured import check_effort
from autonomous_ai_agents.clients.transport import LLMTransport
from autonomous_ai_agents.common.config import (
    Effort,
    Role,
    Settings,
    role_chain,
    settings,
)
from autonomous_ai_agents.common.models import (
    Hotspot,
    Lesson,
    Objective,
    Project,
    ProjectUnderstanding,
    Technique,
    TechniqueMatchRecord,
)
from autonomous_ai_agents.optimization.generate import generate_hypotheses
from autonomous_ai_agents.optimization.sources import GenerateResult, MatchResult
from autonomous_ai_agents.research.playbook import MATCH_MAX_TOKENS, match_techniques


def _checked(
    transport: LLMTransport, config: Settings, role: Role, effort: Effort | None
) -> Effort | None:
    expected = role_chain(config, role)
    if tuple(transport.chain) != expected:
        raise ValueError(
            f"the {role} transport bills {list(transport.chain)}, "
            f"not the {role} chain {list(expected)}"
        )
    return check_effort(effort, transport.chain)


class ClaudeHypothesisGenerator:
    """One ``generate_hypotheses`` request per call, on the generator role.

    Effort and token cap are ``GENERATOR_EFFORT`` and ``GENERATOR_MAX_TOKENS``
    of ``config``; ``sleep`` is the retry backoff.
    """

    def __init__(
        self,
        transport: LLMTransport,
        *,
        config: Settings = settings,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._effort = _checked(transport, config, "generator", config.GENERATOR_EFFORT)
        self._transport, self._config, self._sleep = transport, config, sleep

    def generate(
        self,
        *,
        project: Project,
        understanding: ProjectUnderstanding | None,
        hotspots: Sequence[Hotspot],
        objective: Objective,
        techniques: Sequence[Technique],
        lessons: Sequence[Lesson],  # noqa: ARG002 - W1 (D21)
        avoid_titles: Sequence[str],  # noqa: ARG002 - W1 (D21)
        n: int,
        budget: Budget,
    ) -> GenerateResult:
        notes: list[str] = []
        hypotheses = generate_hypotheses(
            self._transport,
            budget,
            project=project,
            understanding=understanding,
            hotspots=hotspots,
            objective=objective,
            techniques=techniques,
            n=n,
            effort=self._effort,
            max_tokens=self._config.GENERATOR_MAX_TOKENS,
            notes=notes,
            sleep=self._sleep,
            config=self._config,
        )
        return GenerateResult(hypotheses=hypotheses, notes=tuple(notes))


class ClaudeTechniqueMatcher:
    """One ``match_techniques`` request per call (none with no technique), on
    the matcher role at ``MATCHER_EFFORT``; the token cap is the matcher's
    ``MATCH_MAX_TOKENS`` (there is no ``MATCHER_MAX_TOKENS`` setting)."""

    def __init__(
        self,
        transport: LLMTransport,
        *,
        config: Settings = settings,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._effort = _checked(transport, config, "matcher", config.MATCHER_EFFORT)
        self._transport, self._config, self._sleep = transport, config, sleep

    def match(
        self,
        *,
        understanding: ProjectUnderstanding | None,
        hotspots: Sequence[Hotspot],
        techniques: Sequence[Technique],
        k: int,
        budget: Budget,
    ) -> MatchResult:
        notes: list[str] = []
        found = match_techniques(
            self._transport,
            budget,
            understanding=understanding,
            hotspots=hotspots,
            techniques=techniques,
            k=k,
            effort=self._effort,
            max_tokens=MATCH_MAX_TOKENS,
            notes=notes,
            sleep=self._sleep,
            config=self._config,
        )
        matches = tuple(
            TechniqueMatchRecord(
                slug=m.slug,
                fit=m.fit,
                justification_summary=m.justification_summary,
                unmet_preconditions=m.unmet_preconditions,
            )
            for m in found
        )
        return MatchResult(matches=matches, notes=tuple(notes))
