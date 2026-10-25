"""Shared helpers of the discovery experiments (Window 0: E3, E5, E8a).

``test_sweep_live.py`` (E3, blind hypothesis sweep), ``test_ab_live.py`` (E5,
retrieval A/B) and ``test_escalation_live.py`` (E8a, cheap editor first) use:

- Settings: a validated per-run copy with one engine model, alone, is
  ``common.config.role_settings`` on the engine role (``ENGINE_MODEL`` set,
  ``ENGINE_FALLBACKS`` off; the copy is validated again, so an effort a chain
  model refuses fails before any spend). ``model_settings``, the helper it
  was promoted from (U2), is now that call, kept for the suites that still
  name it. The global ``settings`` are never changed.
- Phase 1 (``phase_one``): the project understanding, the profiler hotspots
  and the objective of one corpus repository from the engine's real
  components, without any trial. It is a whole ``Orchestrator.run`` with
  zero candidates through ``corpus.start_loop`` (the factory's real
  preflight, ``ClaudeUnderstander``, baseline and ``CProfiler`` on the
  captured transport, the ``required`` sandbox): connect, understand,
  define, baseline, profile, then no trial, nothing to combine and a
  report-only delivery. That is the cleanest choice because every corpus
  guard (``check_loop_guards``: done, spend matches the wire, repository
  untouched, sandboxed launches) applies unchanged; assembling the factory's
  pieces by hand would duplicate the node logic. Its one paid request is the
  understand call on ``PHASE_ONE_MODEL`` (Sonnet 5.5, no fallbacks): worst
  case ``PHASE_ONE_WORST_USD`` (about 0.16 USD: ``UNDERSTAND_PROMPT_BOUND``
  of prompt, 8000 tokens of output), typically 0.02-0.04 USD.
  ``UNDERSTAND_EFFORT`` and ``UNDERSTAND_MAX_TOKENS`` come from the global
  settings, not the run's copy: ``build_context``'s ``ClaudeUnderstander``
  reads them there (only its transport, hence its chain, is the copy's).
- Caps: every run's cap is the sum of the worst cases (``worst_usd``, the
  real ``preflight_estimate``) of every request the run may send, rounded up
  to 0.05 USD (``ceil_usd``), so no request can be refused for the budget
  and no arm's data is lost because an earlier one spent much. A worst case
  needs a prompt bound: the ``*_PROMPT_BOUND`` constants bound what
  ``call()`` counts for each request (the byte bound plus the allowance; no
  token covers less than a byte), and ``test_discovery_guards`` measures the
  real requests built from the largest facts each corpus repository allows.
  Those facts are ASCII text and bare function or class names; a summary
  heavy in non-ASCII text (escaped to six bytes a character), qualified
  symbol names or many hotspot tags could exceed a bound. Then the request
  is refused before it is sent and recorded as the arm's error, never
  billed over the cap. A transport timeout also charges the attempt's full
  estimate before the retry (``call()``: the money may be gone), so one
  timeout can push a later arm of the same run into a recorded refusal.
- ``run_arm`` / ``generate_arm``: one arm's requests through a transport
  whose chain is that arm's model alone (no fallbacks), with the arm's
  cost, billed models, tokens (thinking tokens from
  ``usage.output_tokens_details.thinking_tokens``, cache reads from
  ``usage.cache_read_input_tokens``) and wall time. A refused or unusable
  arm is recorded with its error; ``check_calls`` then fails the test.
- ``carry``: generated hypotheses as phase-2 candidates, ``hotspot_ids``
  cleared (they name phase 1's hotspot records; the trials node gives a
  hypothesis that names none of the run's hotspots the run's top ones),
  ``efficiency`` ones only (any other class pauses the run for approval).
- ``run_engine``: one whole loop with every corpus guard, its
  ``CorpusOutcome`` and ``EngineRunResult`` handed to the recorder pass or
  fail (a breach is recorded, then raised again); ``budget_flags`` tells a
  loss the cap caused (``budget_exhausted`` in the state, or a trial whose
  error is a cost-cap stop) from a real one.

The knobs, the results file and the summaries live in ``discovery_io``.

API facts relied on (platform.claude.com, read through the claude-api
skill, shared/cost-optimization.md and shared/prompt-caching.md):
``usage.output_tokens_details.thinking_tokens`` meters thinking and is part
of ``output_tokens``; ``usage.cache_read_input_tokens`` counts the tokens
read from the cache.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final

import pytest
from anthropic.types.beta import BetaMessage
from e2e.conftest import Isolation

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.cost import count_margin, preflight_estimate
from autonomous_ai_agents.clients.structured import PROMPT_ALLOWANCE_TOKENS
from autonomous_ai_agents.clients.transport import LLMRequest, LLMTransport
from autonomous_ai_agents.common.config import (
    Effort,
    Settings,
    role_settings,
    settings,
)
from autonomous_ai_agents.common.errors import (
    EngineError,
    LLMRequestError,
    LLMUnavailable,
    UnusableReplyError,
)
from autonomous_ai_agents.common.models import (
    ChangeClass,
    Hotspot,
    Hypothesis,
    ModelPrice,
    Objective,
    Project,
    ProjectUnderstanding,
    Technique,
)
from autonomous_ai_agents.execution.editor import STOP_BUDGET
from autonomous_ai_agents.optimization.generate import (
    GENERATE_MAX_TOKENS,
    generate_hypotheses,
)
from autonomous_ai_agents.orchestrator.main import EngineRunResult
from autonomous_ai_agents.research.playbook import TechniqueMatch

from .conftest import LiveRun, usage_tokens
from .corpus import (
    CorpusOutcome,
    CorpusRepo,
    Loop,
    check_loop_guards,
    outcome_of,
    start_loop,
)

OPUS: Final = "claude-opus-5-5"
SONNET: Final = "claude-sonnet-5-5"
FABLE: Final = "claude-fable-5-1"
PHASE_ONE_MODEL: Final = SONNET
ARM_ERRORS: Final = (EngineError, LLMUnavailable, LLMRequestError, UnusableReplyError)

# What ``call()`` may count, in tokens, for each request on any corpus
# repository (the byte bound plus the allowance, as ``ScriptedTransport``
# counts it); measured with the largest facts in test_discovery_guards.
UNDERSTAND_PROMPT_BOUND: Final = 28_000  # ReadLimits trims each file to 8 KiB
BLIND_PROMPT_BOUND: Final = 26_000  # generator, no techniques, 30 hotspots
CARDS_PROMPT_BOUND: Final = 34_000  # generator with the 3 largest cards
MATCH_PROMPT_BOUND: Final = 86_000  # matcher with the whole playbook
PROBE_PROMPT_BOUND: Final = 70_000  # generator with the whole playbook, no facts


def chain_worst_usd(bound: int, max_tokens: int, models: Sequence[str]) -> float:
    """What ``call()`` checks before a request over ``models`` whose count is
    at most ``bound``: the count, its margin and the allowance at the dearest
    input rate, plus ``max_tokens`` at the output rate, once per model."""
    prompt = bound + count_margin(bound) + PROMPT_ALLOWANCE_TOKENS
    return preflight_estimate(prompt, max_tokens, models, settings.MODEL_PRICING)


def worst_usd(bound: int, max_tokens: int, model: str) -> float:
    """``chain_worst_usd`` on ``model`` alone (no fallbacks)."""
    return chain_worst_usd(bound, max_tokens, (model,))


def ceil_usd(amount: float, step: float = 0.05) -> float:
    """``amount`` rounded up to a multiple of ``step`` (a cap, never below)."""
    return round(math.ceil(round(amount / step, 9)) * step, 2)


PHASE_ONE_WORST_USD: Final = worst_usd(
    UNDERSTAND_PROMPT_BOUND, settings.UNDERSTAND_MAX_TOKENS, PHASE_ONE_MODEL
)
PHASE_ONE_CAP_USD: Final = ceil_usd(PHASE_ONE_WORST_USD)

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def model_settings(
    base: Settings, model: str, *, fallbacks: bool = False, **update: object
) -> Settings:
    """``base`` with ``ENGINE_MODEL`` = ``model`` (fallbacks off unless asked)
    and ``update``: ``role_settings`` on the engine role, validated again;
    ``base`` itself is not changed."""
    return role_settings(
        base, "engine", ENGINE_MODEL=model, ENGINE_FALLBACKS=fallbacks, **update
    )


# ---------------------------------------------------------------------------
# Usage and arms
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Usage:
    """What one answered request reported."""

    model: str
    input_tokens: int
    output_tokens: int
    thinking_tokens: int | None  # None: the response did not say
    cache_read_tokens: int
    cache_write_tokens: int


def usage_of(message: BetaMessage) -> Usage:
    tokens = usage_tokens(message.usage)
    details = message.usage.output_tokens_details
    thinking = None if details is None else details.thinking_tokens
    return Usage(message.model, tokens[0], tokens[1], thinking, tokens[2], tokens[3])


class UsageTap:
    """``LLMTransport`` that keeps the usage of every answered request."""

    def __init__(self, inner: LLMTransport) -> None:
        self._inner = inner
        self.usages: list[Usage] = []

    @property
    def chain(self) -> tuple[str, ...]:
        return self._inner.chain

    @property
    def prices(self) -> Mapping[str, ModelPrice]:
        return self._inner.prices

    def count_input_tokens(self, request: LLMRequest) -> int:
        return self._inner.count_input_tokens(request)

    def send(self, request: LLMRequest) -> BetaMessage:
        message = self._inner.send(request)
        self.usages.append(usage_of(message))
        return message


@dataclass(frozen=True)
class Arm:
    """One generation setting: a model alone (no fallbacks) at one effort."""

    label: str
    model: str
    effort: Effort


@dataclass(frozen=True)
class ArmResult:
    """What one arm produced and spent (``error``: why it produced nothing)."""

    arm: Arm
    hypotheses: tuple[Hypothesis, ...]
    cost_usd: float
    usages: tuple[Usage, ...]
    models: tuple[str, ...]  # the models the recorder billed
    wall_s: float
    error: str | None
    notes: tuple[str, ...] = ()
    matches: tuple[TechniqueMatch, ...] = ()

    @property
    def answered(self) -> bool:
        return bool(self.usages)

    def tokens(self, name: str) -> int:
        return sum(int(getattr(usage, name)) for usage in self.usages)

    @property
    def thinking_tokens(self) -> int | None:
        found = [u.thinking_tokens for u in self.usages]
        if not found or any(t is None for t in found):
            return None
        return sum(t for t in found if t is not None)


@dataclass(frozen=True)
class RepoFacts:
    """What phase 1 learned, as the generator and the matcher take it."""

    project: Project
    understanding: ProjectUnderstanding | None
    hotspots: tuple[Hotspot, ...]
    objective: Objective


Work = Callable[
    [LLMTransport, Settings, list[str]],
    tuple[tuple[Hypothesis, ...], tuple[TechniqueMatch, ...]],
]


def run_arm(arm: Arm, run: LiveRun, base: Settings, work: Work) -> ArmResult:
    """``work`` on the arm's own transport (chain: the arm's model alone)."""
    cfg = role_settings(base, "engine", ENGINE_MODEL=arm.model, ENGINE_FALLBACKS=False)
    tap = UsageTap(run.transport(cfg))
    first = len(run.records)
    notes: list[str] = []
    hypotheses: tuple[Hypothesis, ...] = ()
    matches: tuple[TechniqueMatch, ...] = ()
    error: str | None = None
    started = time.monotonic()
    try:
        hypotheses, matches = work(tap, cfg, notes)
    except ARM_ERRORS as exc:
        error = f"{type(exc).__name__}: {exc}"
    wall = time.monotonic() - started
    records = run.records[first:]
    return ArmResult(
        arm=arm,
        hypotheses=hypotheses,
        cost_usd=math.fsum(r.cost_usd for r in records),
        usages=tuple(tap.usages),
        models=tuple(dict.fromkeys(r.model for r in records)),
        wall_s=wall,
        error=error,
        notes=tuple(notes),
        matches=matches,
    )


def generate_arm(
    arm: Arm,
    run: LiveRun,
    budget: Budget,
    facts: RepoFacts,
    *,
    n: int,
    techniques: Sequence[Technique] = (),
    max_tokens: int = GENERATE_MAX_TOKENS,
    base: Settings = settings,
) -> ArmResult:
    """One ``generate_hypotheses`` call (``techniques=()``: blind) for ``arm``."""

    def work(
        transport: LLMTransport, cfg: Settings, notes: list[str]
    ) -> tuple[tuple[Hypothesis, ...], tuple[TechniqueMatch, ...]]:
        found = generate_hypotheses(
            transport,
            budget,
            project=facts.project,
            understanding=facts.understanding,
            hotspots=facts.hotspots,
            objective=facts.objective,
            techniques=techniques,
            n=n,
            effort=arm.effort,
            max_tokens=max_tokens,
            notes=notes,
            config=cfg,
        )
        return found, ()

    return run_arm(arm, run, base, work)


def check_calls(
    run: LiveRun, budget: Budget, arms: Sequence[ArmResult], *, answered: int = 0
) -> None:
    """The guards after an experiment's requests: every arm answered and
    billed its own model only; ``answered`` more requests (graders) got an
    answer; the wire, the recorder and the budget agree and hold the cap."""
    for result in arms:
        assert result.answered, f"{result.arm.label} got no answer: {result.error}"
        assert set(result.models) == {result.arm.model}, (result.arm, result.models)
    assert len(run.capture.messages()) == len(run.records)
    ok = [e for e in run.capture.messages() if e.status == 200]
    assert len(ok) >= len(arms) + answered, run.api_errors()
    assert run.spent_usd <= run.cap_usd
    assert budget.spent_usd == pytest.approx(run.spent_usd, rel=1e-9, abs=1e-12)


# ---------------------------------------------------------------------------
# Phase 1 and the hand-over to phase 2
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PhaseOne:
    """A baseline run without any trial: its loop, its facts, its cost."""

    loop: Loop
    facts: RepoFacts
    cost_usd: float


def start_phase_one(
    repo: CorpusRepo, run: LiveRun, root: Path, isolation: Isolation, cfg: Settings
) -> Loop:
    """``repo`` wired like a corpus run on ``cfg``, with zero candidates."""
    root.mkdir(parents=True, exist_ok=True)
    loop = start_loop(repo, run, root, isolation, mode="blind", cfg=cfg, candidates=())
    return replace(loop, cap_usd=min(PHASE_ONE_CAP_USD, run.cap_usd))


def read_phase_one(loop: Loop, run: LiveRun, result: EngineRunResult) -> PhaseOne:
    state = result.state
    if not state["objectives"]:
        raise ValueError("phase one ended without an objective")
    facts = RepoFacts(
        project=state["project"],
        understanding=state["understanding"],
        hotspots=tuple(state["hotspots"]),
        objective=state["objectives"][0],
    )
    return PhaseOne(loop, facts, run.spent_usd)


def phase_one(
    repo: CorpusRepo, run: LiveRun, root: Path, isolation: Isolation, cfg: Settings
) -> PhaseOne:
    """Phase 1 as the run's first spend, with every corpus guard."""
    if run.records:
        raise ValueError("phase one must be the first spend of its run")
    loop = start_phase_one(repo, run, root, isolation, cfg)
    result = loop.run()
    check_loop_guards(loop, run, result, isolation)
    return read_phase_one(loop, run, result)


def check_untouched(phase: PhaseOne) -> None:
    """The user's repository is exactly as phase 1 found it."""
    assert phase.loop.user.snapshot() == phase.loop.before


def carry(hypotheses: Sequence[Hypothesis]) -> tuple[Hypothesis, ...]:
    """Phase-1 hypotheses as phase-2 candidates: ``hotspot_ids`` cleared, and
    only the ``efficiency`` ones. A ``behaviour`` or ``novel`` hypothesis
    (the generator never classes one below its card, and the playbook's
    behaviour cards are its distractors) ends the run at the approval gate,
    ``needs_approval``, which no unattended run can answer."""
    return tuple(
        h.model_copy(update={"hotspot_ids": ()})
        for h in hypotheses
        if h.change_class is ChangeClass.efficiency
    )


BUDGET_ERROR_MARKERS: Final = (
    "BudgetExceeded",
    "the run's cost cap",  # the editor's STOP_BUDGET text
    f"the editor stopped ({STOP_BUDGET})",
)


@dataclass(frozen=True)
class BudgetFlags:
    """Whether the cap shaped a run's outcome (``None``: no state to read)."""

    budget_exhausted: bool | None
    trial_budget_error: bool


def budget_flags(result: EngineRunResult | None) -> BudgetFlags:
    """The state's ``budget_exhausted``, and whether any trial's error names
    a cost-cap stop (``BudgetExceeded`` or the editor's budget stop)."""
    if result is None:
        return BudgetFlags(None, False)
    state = result.state
    errors = [t.error or "" for t in state["trials"]]
    hit = any(marker in error for error in errors for marker in BUDGET_ERROR_MARKERS)
    return BudgetFlags(bool(state["budget_exhausted"]), hit)


def engine_outcome(
    loop: Loop,
    run: LiveRun,
    result: EngineRunResult | None,
    *,
    model: str,
    guard: str,
) -> CorpusOutcome:
    found = outcome_of(loop.repo, run, result, guard=guard, mode=loop.mode)
    return replace(found, engine_model=model)


def run_engine(
    loop: Loop,
    run: LiveRun,
    isolation: Isolation,
    *,
    model: str,
    record: Callable[[CorpusOutcome, EngineRunResult | None], None],
) -> CorpusOutcome:
    """The whole loop and every corpus guard; the outcome is recorded pass
    or fail (a breach is recorded, then raised again)."""
    result: EngineRunResult | None = None
    try:
        result = loop.run()
        check_loop_guards(loop, run, result, isolation)
    except BaseException as exc:
        guard = f"breach: {type(exc).__name__}: {exc}"
        record(engine_outcome(loop, run, result, model=model, guard=guard), result)
        raise
    outcome = engine_outcome(loop, run, result, model=model, guard="ok")
    record(outcome, result)
    return outcome
