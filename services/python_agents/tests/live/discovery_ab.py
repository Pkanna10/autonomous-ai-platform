"""E5, the retrieval A/B: does a matched playbook raise executed wins?

For every repository (benchmark slowdowns and controls, the hard corpus)
and repetition (``$LIVE_AB_REPS``, default and at most 2: a third would
take the suite past the 150 USD ceiling), phase 1 runs once
and two arms generate ``AB_N`` hypotheses with Sonnet 5.5 at medium effort,
no fallbacks:

- A (``blind_arm``): ``generate_hypotheses`` with no techniques;
- B (``retrieval_arm``): ``match_techniques`` (k = ``AB_K``) over the shipped
  playbook, then ``generate_hypotheses`` with the matched cards only.

Phase 1 and the generation share one run capped at ``AB_GEN_CAP_USD``, the
sum of the worst cases of its four requests (understand, A's generation,
B's matcher, B's generation), so B, which always runs last, can never be
refused for the budget. The matched cards reach only the generator: the
engine's editors get the run's top-5 hotspot brief (the trials node's
fallback for a hypothesis that names none of the run's hotspots).

Each arm's hypotheses (``hotspot_ids`` cleared) are the candidates of one
whole engine loop on ``ENGINE_MODEL`` Sonnet 5.5, no fallbacks, capped at
``$LIVE_AB_RUN_CAP_USD`` (default 1 USD), with every corpus guard. An arm
that produced no efficiency-class hypothesis runs no loop and counts as a
loss (a behaviour or novel one would pause the run for approval; the row
counts what was dropped).

Recorded per run, never asserted: win (a delivered branch), the primary
metric's gain, whether it reached the repository's reference gain (the
corpus's known-fix rule for blind runs), cost, and for B the matched slugs
and whether a distractor (``tests/research/distractors.json``) was among
them. The summary pairs the arms per (repository, repetition) on the
slowdowns whose both runs held every guard (a breach, or an arm that never
ran, excludes the task, and the count is printed): the discordant counts b
(A won, B lost) and c (A lost, B won)
and an exact two-sided McNemar p-value, then the research plan's rule: B
must beat A by at least 3 discordant tasks (c - b >= 3), else the paper
pipeline is deprioritised behind the playbook, lessons and evolution.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Final

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.structured import strict_json
from autonomous_ai_agents.clients.transport import LLMTransport
from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.common.models import Hypothesis, Technique
from autonomous_ai_agents.optimization.generate import generate_hypotheses
from autonomous_ai_agents.orchestrator.main import EngineRunResult
from autonomous_ai_agents.research.playbook import (
    MATCH_MAX_TOKENS,
    TechniqueMatch,
    match_techniques,
)

from .conftest import TESTS_DIR, LiveRun
from .corpus import CORPUS, HARD_CORPUS, CorpusOutcome, CorpusRepo
from .discovery import (
    BLIND_PROMPT_BOUND,
    CARDS_PROMPT_BOUND,
    MATCH_PROMPT_BOUND,
    PHASE_ONE_WORST_USD,
    SONNET,
    Arm,
    ArmResult,
    RepoFacts,
    budget_flags,
    carry,
    ceil_usd,
    generate_arm,
    model_settings,
    run_arm,
    worst_usd,
)
from .discovery_io import (
    ResultsSink,
    cells,
    env_number,
    env_whole,
    flag,
    per,
    rate,
    write_markdown,
)

REPS_ENV: Final = "LIVE_AB_REPS"
RUN_CAP_ENV: Final = "LIVE_AB_RUN_CAP_USD"
AB_REPS: Final = 2
AB_MAX_REPS: Final = 2
AB_RUN_CAP_USD: Final = 1.0
MAX_RUN_CAP_USD: Final = 5.0
AB_N: Final = 3
AB_GENERATE_MAX_TOKENS: Final = 8000
"""Both arms' generation ``max_tokens`` (the generator's default is 16000):
three intent-level ideas fit easily, and it halves the output side of the
shared run's worst case. The same for both arms, so the comparison is fair."""
AB_K: Final = 3
AB_ARM: Final = Arm("sonnet-5-5-medium", SONNET, "medium")
AB_GEN_CAP_USD: Final = ceil_usd(
    PHASE_ONE_WORST_USD
    + worst_usd(BLIND_PROMPT_BOUND, AB_GENERATE_MAX_TOKENS, AB_ARM.model)
    + worst_usd(MATCH_PROMPT_BOUND, MATCH_MAX_TOKENS, AB_ARM.model)
    + worst_usd(CARDS_PROMPT_BOUND, AB_GENERATE_MAX_TOKENS, AB_ARM.model)
)
"""Phase 1, A's generation, B's matcher and B's generation at their worst."""
AB_REPOS: Final = (*CORPUS, *HARD_CORPUS)
DISTRACTORS_PATH: Final = TESTS_DIR / "research" / "distractors.json"
MIN_DISCORDANT_LEAD: Final = 3


@dataclass(frozen=True)
class AbPlan:
    reps: int
    run_cap: float


def ab_plan(environ: Mapping[str, str]) -> AbPlan:
    """Every knob, validated strictly (in the module fixture, before any spend)."""
    return AbPlan(
        reps=env_whole(environ, REPS_ENV, AB_REPS, low=1, high=AB_MAX_REPS),
        run_cap=env_number(environ, RUN_CAP_ENV, AB_RUN_CAP_USD, high=MAX_RUN_CAP_USD),
    )


def ab_need(plan: AbPlan) -> float:
    """The sum of the caps the suite asks the ledger for: per task the shared
    generation run plus both engine runs."""
    return plan.reps * len(AB_REPOS) * (AB_GEN_CAP_USD + 2 * plan.run_cap)


def ab_settings(base: Settings) -> Settings:
    """The engine runs' settings: Sonnet 5.5, no fallbacks."""
    return model_settings(base, AB_ARM.model)


def load_distractors(path: Path = DISTRACTORS_PATH) -> frozenset[str]:
    """The playbook's distractor slugs, read strictly."""
    data = strict_json(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"version", "slugs"}:
        raise ValueError(f"{path}: expected {{'version': 1, 'slugs': [...]}}")
    slugs = data["slugs"]
    if data["version"] != 1 or not isinstance(slugs, list):
        raise ValueError(f"{path}: expected version 1 and a list of slugs")
    if not all(isinstance(s, str) for s in slugs):
        raise ValueError(f"{path}: every slug must be a string")
    return frozenset(s for s in slugs if isinstance(s, str))


def blind_arm(
    run: LiveRun, budget: Budget, facts: RepoFacts, *, base: Settings = settings
) -> ArmResult:
    """Arm A: ``AB_N`` hypotheses with no techniques."""
    return generate_arm(
        AB_ARM, run, budget, facts, n=AB_N, max_tokens=AB_GENERATE_MAX_TOKENS, base=base
    )


def retrieval_arm(
    run: LiveRun,
    budget: Budget,
    facts: RepoFacts,
    *,
    playbook: Sequence[Technique],
    base: Settings = settings,
) -> ArmResult:
    """Arm B: match ``AB_K`` cards, then generate from the matched cards."""

    def work(
        transport: LLMTransport, cfg: Settings, notes: list[str]
    ) -> tuple[tuple[Hypothesis, ...], tuple[TechniqueMatch, ...]]:
        matches = match_techniques(
            transport,
            budget,
            understanding=facts.understanding,
            hotspots=facts.hotspots,
            techniques=playbook,
            k=AB_K,
            effort=AB_ARM.effort,
            notes=notes,
            config=cfg,
        )
        by_slug = {t.id: t for t in playbook}
        cards = [by_slug[m.slug] for m in matches if m.slug in by_slug]
        found = generate_hypotheses(
            transport,
            budget,
            project=facts.project,
            understanding=facts.understanding,
            hotspots=facts.hotspots,
            objective=facts.objective,
            techniques=cards,
            n=AB_N,
            effort=AB_ARM.effort,
            max_tokens=AB_GENERATE_MAX_TOKENS,
            notes=notes,
            config=cfg,
        )
        return found, matches

    return run_arm(AB_ARM, run, base, work)


@dataclass(frozen=True)
class AbRow:
    """One arm of one (repository, repetition) (recorded, never asserted)."""

    repo: str
    kind: str
    category: str
    rep: int
    arm: str  # "A" blind, "B" retrieval
    status: str  # the engine status, "error", or "no_hypotheses"
    win: bool
    kept: tuple[str, ...]
    gain_pct: float | None
    reached_fix: bool
    engine_cost_usd: float
    generation_cost_usd: float
    candidates: int  # handed to the loop (efficiency class only)
    dropped: int  # generated, but behaviour or novel: never handed over
    matched: tuple[str, ...]
    distractor_matched: bool | None  # None: arm A, or nothing was matched
    engine_model: str
    served_models: tuple[str, ...]
    guard: str
    generation_error: str | None
    budget_exhausted: bool | None  # the state's flag; None: no loop ran
    trial_budget_error: bool  # a trial's error is a cost-cap stop

    def record(self) -> dict[str, object]:
        return {"experiment": "E5-ab", **asdict(self)}


def ab_row(
    repo: CorpusRepo,
    rep: int,
    arm: str,
    produced: ArmResult,
    outcome: CorpusOutcome | None,
    distractors: Collection[str],
    result: EngineRunResult | None = None,
) -> AbRow:
    """The row of one arm; ``outcome`` ``None``: no loop ran (no candidate).
    ``result`` tells a loss the cap caused from a real one."""
    budget = budget_flags(result)
    matched = tuple(m.slug for m in produced.matches)
    hit = bool(set(matched) & set(distractors)) if arm == "B" and matched else None
    return AbRow(
        repo=repo.name,
        kind=repo.kind,
        category=repo.category,
        rep=rep,
        arm=arm,
        status="no_hypotheses" if outcome is None else outcome.status,
        win=outcome is not None and outcome.delivered,
        kept=() if outcome is None else outcome.kept,
        gain_pct=None if outcome is None else outcome.gain_pct,
        reached_fix=outcome is not None and outcome.reached_fix,
        engine_cost_usd=0.0 if outcome is None else outcome.cost_usd,
        generation_cost_usd=produced.cost_usd,
        candidates=len(carry(produced.hypotheses)),
        dropped=len(produced.hypotheses) - len(carry(produced.hypotheses)),
        matched=matched,
        distractor_matched=hit,
        engine_model=AB_ARM.model if outcome is None else outcome.engine_model,
        served_models=() if outcome is None else outcome.served_models,
        guard="ok" if outcome is None else outcome.guard,
        generation_error=produced.error,
        budget_exhausted=budget.budget_exhausted,
        trial_budget_error=budget.trial_budget_error,
    )


def mcnemar_exact(b: int, c: int) -> float:
    """Exact two-sided McNemar p-value: twice the binomial(b + c, 1/2) tail
    at min(b, c), at most 1."""
    if b < 0 or c < 0:
        raise ValueError(f"discordant counts must be >= 0, got {b} and {c}")
    n = b + c
    tail = sum(Fraction(math.comb(n, i), 2**n) for i in range(min(b, c) + 1))
    return float(min(Fraction(1), 2 * tail))


Pairs = dict[tuple[str, int], tuple[bool, bool]]


def _first_rows(rows: Sequence[AbRow]) -> dict[tuple[str, int, str], AbRow]:
    seen: dict[tuple[str, int, str], AbRow] = {}
    for row in rows:
        if row.kind != "control":
            seen.setdefault((row.repo, row.rep, row.arm), row)
    return seen


def discordant(rows: Sequence[AbRow]) -> tuple[Pairs, int, int]:
    """Paired (A win, B win) per slowdown task whose two rows (the first per
    arm) both held every guard; b and c."""
    seen = _first_rows(rows)
    pairs: Pairs = {}
    for (repo, rep, arm), row in seen.items():
        other = seen.get((repo, rep, "B"))
        if arm == "A" and other is not None and row.guard == other.guard == "ok":
            pairs[(repo, rep)] = (row.win, other.win)
    b = sum(a and not w for a, w in pairs.values())
    c = sum(w and not a for a, w in pairs.values())
    return pairs, b, c


def excluded_tasks(rows: Sequence[AbRow]) -> int:
    """Slowdown tasks with a row that ``discordant`` could not pair."""
    tasks = {(repo, rep) for repo, rep, _ in _first_rows(rows)}
    return len(tasks) - len(discordant(rows)[0])


def _arm_line(arm: str, rows: Sequence[AbRow]) -> list[object]:
    slow = [r for r in rows if r.kind != "control"]
    wins = sum(r.win for r in slow)
    spend = math.fsum(r.engine_cost_usd + r.generation_cost_usd for r in slow)
    matched = [r for r in rows if r.matched]
    distractor = sum(r.distractor_matched is True for r in matched)
    return [
        arm,
        rate(wins, len(slow)),
        rate(sum(r.reached_fix for r in slow), len(slow)),
        per(spend, wins),
        rate(distractor, len(matched)) if arm == "B" else "-",
    ]


def _cap_hit(row: AbRow) -> str:
    """``yes`` when the cap, not the idea, may have decided the loss."""
    if row.budget_exhausted is None:
        return "-"
    return flag(row.budget_exhausted or row.trial_budget_error)


def render_ab(rows: Sequence[AbRow]) -> str:
    lines = ["## Retrieval A/B (E5)", ""]
    if not rows:
        return "\n".join([*lines, "No A/B task finished."])
    lines += [
        "| repo | rep | arm | status | win | gain % | reached ref gain "
        "| engine USD | generation USD | matched | distractor | cap hit | guards |",
        "| --- | ---: | --- | --- | --- | ---: | --- | ---: | ---: | --- | --- "
        "| --- | --- |",
    ]
    for r in rows:
        gain = "-" if r.gain_pct is None else f"{r.gain_pct:.1f}"
        lines.append(
            cells(
                [
                    r.repo,
                    r.rep,
                    r.arm,
                    r.status,
                    flag(r.win),
                    gain,
                    flag(r.reached_fix),
                    f"{r.engine_cost_usd:.4f}",
                    f"{r.generation_cost_usd:.4f}",
                    ", ".join(r.matched) or "-",
                    flag(r.distractor_matched),
                    _cap_hit(r),
                    r.guard if r.generation_error is None else r.generation_error,
                ]
            )
        )
    lines += [
        "",
        "| arm | win rate | reference-gain rate | cost per win USD "
        "| distractor-match rate |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for arm in ("A", "B"):
        group = [r for r in rows if r.arm == arm]
        if group:
            lines.append(cells(_arm_line(arm, group)))
    pairs, b, c = discordant(rows)
    lines += ["", "| repo | paired outcomes (rep: A win, B win) |", "| --- | --- |"]
    for repo in dict.fromkeys(name for name, _ in pairs):
        found = [
            f"{rep}: {flag(a)}, {flag(w)}"
            for (n, rep), (a, w) in pairs.items()
            if n == repo
        ]
        lines.append(cells([repo, "; ".join(found)]))
    controls = [r for r in rows if r.kind == "control"]
    false_wins = {
        arm: rate(
            sum(r.win for r in controls if r.arm == arm),
            sum(r.arm == arm for r in controls),
        )
        for arm in ("A", "B")
    }
    lead = c - b
    verdict = (
        f"c - b = {lead}: B beats A by at least {MIN_DISCORDANT_LEAD}"
        if lead >= MIN_DISCORDANT_LEAD
        else f"c - b = {lead}: B does not beat A by {MIN_DISCORDANT_LEAD}; "
        "deprioritise the paper pipeline behind playbook, lessons and evolution"
    )
    lines += [
        "",
        f"Paired slowdown tasks: {len(pairs)} (excluded {excluded_tasks(rows)} "
        "slowdown task(s): a guard breach, or an arm that never ran); "
        f"discordant b = {b}, c = {c}; exact two-sided McNemar p = "
        f"{mcnemar_exact(b, c):.4f}.",
        f"Decision rule: B must beat A by at least {MIN_DISCORDANT_LEAD} "
        f"discordant tasks. {verdict}.",
        f"Control false-win rate: A {false_wins['A']}, B {false_wins['B']}.",
        "Scope: the matched cards reach only the generator; every editor gets "
        "the run's top-5 hotspot brief, in both arms.",
    ]
    return "\n".join(lines)


@dataclass
class AbRecorder:
    """The module's rows; ``finish`` writes the summary once."""

    plan: AbPlan
    sink: ResultsSink
    distractors: frozenset[str]
    rows: list[AbRow] = field(default_factory=list)

    def record(
        self,
        repo: CorpusRepo,
        rep: int,
        arm: str,
        produced: ArmResult,
        outcome: CorpusOutcome | None,
        result: EngineRunResult | None = None,
        *,
        run: LiveRun,
    ) -> None:
        row = ab_row(repo, rep, arm, produced, outcome, self.distractors, result)
        self.rows.append(row)
        self.sink.write(row.record())
        run.note(f"ab {row.repo} rep {row.rep} arm {row.arm}: win {flag(row.win)}")

    def finish(self, echo: Callable[[str], None]) -> None:
        if self.rows:
            write_markdown(
                "Retrieval A/B", render_ab(self.rows), self.sink.environ, echo
            )
