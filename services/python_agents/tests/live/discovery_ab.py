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
pipeline is deprioritised behind the playbook, lessons and evolution. B's
cards are the playbook's, so a win shows that retrieval helps, not that
paper-derived cards do; a loss is the stronger signal, since paper cards
would reach the generator the same way and are noisier.

**Arm P** (V8, E3; ``$LIVE_AB_SET=v2-p``, the ``ab-v2-p`` suite): on corpus
v2's ``deep``, ``misleading`` and ``uncommon`` slowdowns, where textbook
fixes fall short, arm P replaces B: the engine's ``IdeaPipelineGenerator``
on phase 1's facts and the hot code at phase 1's base commit (read through
the factory's ``repo_reader`` with the run's protected patterns), on the
lane, leap and reviewer transports ``corpus.role_wiring`` captures on the
shared run, the role models and limits of the global settings, no fallback
(no code context: no request, and the guard fails the arm). The shared run's
cap adds the pipeline's every request at D55's prompt bounds as E0b
re-derived them (D61; ``AB_P_GEN_CAP_USD``); P's ideas then run one engine
loop, as A's do. The summary pairs A with P; E3 is informational (no
decision rides on it).
"""

from __future__ import annotations

import argparse
import math
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from fractions import Fraction
from pathlib import Path
from typing import Final, Literal

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.structured import strict_json
from autonomous_ai_agents.clients.transport import LLMTransport
from autonomous_ai_agents.common.config import (
    PIPELINE_ROLES,
    Settings,
    role_chain,
    settings,
)
from autonomous_ai_agents.common.models import Hypothesis, Technique
from autonomous_ai_agents.optimization.generate import generate_hypotheses
from autonomous_ai_agents.optimization.idea_pipeline import IdeaPipelineGenerator
from autonomous_ai_agents.orchestrator.factory import repo_reader
from autonomous_ai_agents.orchestrator.main import EngineRunResult
from autonomous_ai_agents.orchestrator.nodes import NodeContext
from autonomous_ai_agents.research.playbook import (
    MATCH_MAX_TOKENS,
    TechniqueMatch,
    match_techniques,
)

from .conftest import TESTS_DIR, LiveRun
from .corpus import CORPUS, HARD_CORPUS, CorpusOutcome, CorpusRepo, role_wiring
from .discovery import (
    BLIND_PROMPT_BOUND,
    CARDS_PROMPT_BOUND,
    MATCH_PROMPT_BOUND,
    PHASE_ONE_WORST_USD,
    SONNET,
    Arm,
    ArmResult,
    RepoFacts,
    Usage,
    UsageTap,
    budget_flags,
    carry,
    ceil_usd,
    chain_worst_usd,
    check_calls,
    generate_arm,
    model_settings,
    run_arm,
    worst_usd,
)
from .discovery_corpus import of_group
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
SET_ENV: Final = "LIVE_AB_SET"
P_SET: Final = "v2-p"  # E3: arms A and P on E3_GROUPS (unset: E5, arms A and B)
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
E2C_GENERATOR_N: Final = 10  # E2c's arm A: today's generator at GENERATOR_N=10
E3_GROUPS: Final = ("deep", "misleading", "uncommon")
AB_V2_P_REPOS: Final = tuple(r for group in E3_GROUPS for r in of_group(group))
P_ARM: Final = Arm("idea-pipeline", AB_ARM.model, AB_ARM.effort)
"""Arm P's label; its run settings are A's, its role models the pipeline's."""
IDEAS_LANE_PROMPT_BOUND: Final = 38_000  # S1, a lens or the leap: E0b max 35,686
IDEAS_REVIEW_PROMPT_BOUND: Final = 44_000  # the reviewer, 16 ideas: E0b max 39,463
"""D55's bounds, counted with margin and allowance, re-derived from E0b's
counted maxima on the ten OSS libraries (D61; both mistune) plus margin; the
one source (``ideas_probe`` imports them): a larger count is refused before
it is sent (S1 recorded as the arm's error, S2 skipped whole)."""


def pipeline_settings(base: Settings) -> Settings:
    """Arm P's copy: A's (Sonnet 5.5 alone) with ``IDEA_PIPELINE`` on."""
    return model_settings(base, AB_ARM.model, IDEA_PIPELINE=True)


def pipeline_worst_usd(cfg: Settings) -> float:
    """One pipeline call at every request's worst: S1 and each lens on the
    lane role, the leap (``IDEAS_LEAP_N``) and the reviewer (``IDEAS_REVIEW``)."""
    bound = IDEAS_LANE_PROMPT_BOUND
    lane = chain_worst_usd(bound, cfg.IDEAS_LANE_MAX_TOKENS, role_chain(cfg, "lane"))
    leap = chain_worst_usd(bound, cfg.IDEAS_LEAP_MAX_TOKENS, role_chain(cfg, "leap"))
    review = chain_worst_usd(
        IDEAS_REVIEW_PROMPT_BOUND,
        cfg.IDEAS_REVIEWER_MAX_TOKENS,
        role_chain(cfg, "reviewer"),
    )
    return (
        (1 + len(cfg.IDEAS_LENSES)) * lane
        + (leap if cfg.IDEAS_LEAP_N else 0.0)
        + (review if cfg.IDEAS_REVIEW else 0.0)
    )


AB_P_GEN_CAP_USD: Final = ceil_usd(
    PHASE_ONE_WORST_USD
    + worst_usd(BLIND_PROMPT_BOUND, AB_GENERATE_MAX_TOKENS, AB_ARM.model)
    + pipeline_worst_usd(pipeline_settings(settings))
)
"""Phase 1, A's generation and arm P's pipeline at their worst."""


@dataclass(frozen=True)
class AbPlan:
    reps: int
    run_cap: float
    pipeline: bool = False  # E3: arm P replaces B on AB_V2_P_REPOS

    @property
    def arms(self) -> tuple[str, str]:
        return ("A", "P") if self.pipeline else ("A", "B")

    @property
    def repos(self) -> tuple[CorpusRepo, ...]:
        return AB_V2_P_REPOS if self.pipeline else AB_REPOS

    @property
    def gen_cap(self) -> float:
        return AB_P_GEN_CAP_USD if self.pipeline else AB_GEN_CAP_USD


def ab_plan(environ: Mapping[str, str]) -> AbPlan:
    """Every knob, validated strictly (in the module fixture, before any spend)."""
    chosen = environ.get(SET_ENV, "")
    if SET_ENV in environ and chosen != P_SET:
        raise ValueError(f"{SET_ENV} must be {P_SET!r} or unset, got {chosen!r}")
    return AbPlan(
        reps=env_whole(environ, REPS_ENV, AB_REPS, low=1, high=AB_MAX_REPS),
        run_cap=env_number(environ, RUN_CAP_ENV, AB_RUN_CAP_USD, high=MAX_RUN_CAP_USD),
        pipeline=chosen == P_SET,
    )


def ab_need(plan: AbPlan) -> float:
    """The sum of the caps the suite asks the ledger for: per task the shared
    generation run plus both engine runs."""
    return plan.reps * len(plan.repos) * (plan.gen_cap + 2 * plan.run_cap)


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


def withheld(
    context: NodeContext, extra_protected: Sequence[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """What the engine's own generate call never shows (nodes.py):
    ``protected`` (the context's patterns plus the run's ``extra_protected``,
    the resolved workload and benchmark files and define's frozen ones) and
    ``read_deny`` (the quality check's frozen paths)."""
    protected = (*context.protected_patterns, *extra_protected)
    quality = context.quality
    return protected, (() if quality is None else quality.frozen_paths)


def pipeline_arm(
    run: LiveRun,
    budget: Budget,
    facts: RepoFacts,
    *,
    commit: str,
    protected: Sequence[str],
    read_deny: Sequence[str] = (),
    n: int = AB_N,
    base: Settings = settings,
) -> ArmResult:
    """Arm P: one ``IdeaPipelineGenerator`` call on ``facts`` and the code at
    ``commit`` (``protected`` and ``read_deny`` unread, from ``withheld``),
    ``n`` obvious ideas plus its portfolio, every role on its transport from
    ``role_wiring``, billed on ``run``."""
    usages: list[Usage] = []

    def work(
        _transport: LLMTransport, cfg: Settings, notes: list[str]
    ) -> tuple[tuple[Hypothesis, ...], tuple[TechniqueMatch, ...]]:
        on = pipeline_settings(cfg)
        wired = role_wiring(run, "wired", editor=False, cfg=on)
        taps = {role: UsageTap(wired[role]) for role in PIPELINE_ROLES}
        try:
            found = IdeaPipelineGenerator(taps, reader=repo_reader, config=on).generate(
                project=facts.project, understanding=facts.understanding,
                hotspots=facts.hotspots, objective=facts.objective, techniques=(),
                lessons=(), avoid_titles=(), n=n, budget=budget, commit=commit,
                protected=protected, read_deny=read_deny,
            )  # fmt: skip
        finally:
            usages.extend(u for tap in taps.values() for u in tap.usages)
        notes.extend(found.notes)
        return found.hypotheses, ()

    produced = run_arm(P_ARM, run, base, work, project=facts.project)
    return replace(produced, usages=tuple(usages))


def check_arm_calls(
    run: LiveRun, budget: Budget, arms: Mapping[str, ArmResult]
) -> None:
    """``check_calls`` over the arms, arm P answered on its roles' models."""
    pipeline = arms.get("P")
    if pipeline is not None:
        label = pipeline.arm.label
        assert pipeline.answered, f"{label} got no answer: {pipeline.error}"
        cfg = pipeline_settings(settings)
        roles = {model for role in PIPELINE_ROLES for model in role_chain(cfg, role)}
        assert set(pipeline.models) <= roles, (label, pipeline.models)
    plain = [result for label, result in arms.items() if label != "P"]
    check_calls(run, budget, plain, answered=pipeline is not None)


@dataclass(frozen=True)
class AbRow:
    """One arm of one (repository, repetition) (recorded, never asserted)."""

    repo: str
    kind: str
    category: str
    rep: int
    arm: str  # "A" blind, "B" retrieval, "P" the idea pipeline
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


def discordant(rows: Sequence[AbRow], versus: str = "B") -> tuple[Pairs, int, int]:
    """Paired (A win, ``versus`` win) per slowdown task whose two rows (the
    first per arm) both held every guard; b and c."""
    seen = _first_rows(rows)
    pairs: Pairs = {}
    for (repo, rep, arm), row in seen.items():
        other = seen.get((repo, rep, versus))
        if arm == "A" and other is not None and row.guard == other.guard == "ok":
            pairs[(repo, rep)] = (row.win, other.win)
    b = sum(a and not w for a, w in pairs.values())
    c = sum(w and not a for a, w in pairs.values())
    return pairs, b, c


def excluded_tasks(rows: Sequence[AbRow], versus: str = "B") -> int:
    """Slowdown tasks with a row that ``discordant`` could not pair."""
    tasks = {(repo, rep) for repo, rep, _ in _first_rows(rows)}
    return len(tasks) - len(discordant(rows, versus)[0])


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
    """E5's summary, or E3's when arm P ran (A paired with P, no decision)."""
    other = "P" if any(r.arm == "P" for r in rows) else "B"
    title = "Idea pipeline A/B (E3)" if other == "P" else "Retrieval A/B (E5)"
    lines = [f"## {title}", ""]
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
    for arm in ("A", other):
        group = [r for r in rows if r.arm == arm]
        if group:
            lines.append(cells(_arm_line(arm, group)))
    pairs, b, c = discordant(rows, other)
    lines += [
        "",
        f"| repo | paired outcomes (rep: A win, {other} win) |",
        "| --- | --- |",
    ]
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
        for arm in ("A", other)
    }
    lead = c - b
    paired = (
        f"Paired slowdown tasks: {len(pairs)} (excluded "
        f"{excluded_tasks(rows, other)} slowdown task(s): a guard breach, or an "
        f"arm that never ran); discordant b = {b}, c = {c}; exact two-sided "
        f"McNemar p = {mcnemar_exact(b, c):.4f}."
    )
    if other == "P":
        return "\n".join([
            *lines, "", paired,
            f"c - b = {lead}: P against A on v2's {', '.join(E3_GROUPS)} groups, "
            "where textbook fixes fall short (E3, informational: no decision "
            "rides on it).",
            f"Control false-win rate: A {false_wins['A']}, P {false_wins['P']}.",
        ])  # fmt: skip
    verdict = (
        f"c - b = {lead}: B beats A by at least {MIN_DISCORDANT_LEAD}: "
        "retrieved playbook cards help; paper-derived cards are untested"
        if lead >= MIN_DISCORDANT_LEAD
        else f"c - b = {lead}: B does not beat A by {MIN_DISCORDANT_LEAD}; "
        "deprioritise the paper pipeline behind playbook, lessons and evolution "
        "(retrieved playbook cards did not help, and paper cards would reach "
        "the generator the same way)"
    )
    lines += [
        "",
        paired,
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


def ab_decision(b: int, c: int, controls_a: int, controls_b: int) -> bool:
    """The A/B rule, pooled: B beats A by at least ``MIN_DISCORDANT_LEAD``
    discordant tasks (``c - b``) and has no more control false wins than A."""
    if min(b, c, controls_a, controls_b) < 0:
        raise ValueError(f"counts must be >= 0, got {(b, c, controls_a, controls_b)}")
    return c - b >= MIN_DISCORDANT_LEAD and controls_b <= controls_a


# ---------------------------------------------------------------------------
# oss-ab --from-results (V4 amended): E2 and E2c from the oss suite's results
# artifacts, offline. Run from services/python_agents/tests:
#   uv run python -m live.discovery_ab --from-results --arm-a A1 A2 \
#     --arm-p P1 P2 --controls-a CA --controls-p CP [--rule e2|e2c]
# Each --arm file is one dispatch's live-results.jsonl (one arm, one
# repetition, in order); the controls files are the corpus suite's
# corpus_select=controls dispatches. Nothing is sent. A task's call uses
# the project floor (``project_floor_pct``: the floor the engine judged the
# primary metric with, calibrated on wall time, D41 c and D42), E2's
# pre-registered floor; each combination's own noise floor is shown only.
# ---------------------------------------------------------------------------

Rule = Literal["e2", "e2c"]
Call = Literal["b", "c", "tie", "excluded"]


@dataclass(frozen=True)
class ResultRow:
    """One run of a results artifact, as the pairing reads it."""

    repo: str
    kind: str
    guard: str
    mode: str
    engine_model: str
    delivered: bool
    idea_pipeline: bool
    portfolio_rounds: int
    generator_n: int
    gain_pct: float | None
    floor_pct: float | None  # the combination's noise floor (shown only)
    project_floor_pct: float | None  # the project floor (the call)


def _text(data: Mapping[str, object], key: str, where: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{where}: {key} must be a string")
    return value


def _flag(data: Mapping[str, object], key: str, where: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{where}: {key} must be true or false")
    return value


def _whole(data: Mapping[str, object], key: str, where: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{where}: {key} must be a whole number")
    return value


def _number(data: Mapping[str, object], key: str, where: str) -> float | None:
    if key not in data:
        raise ValueError(f"{where}: {key} is missing (an older harness)")
    value = data[key]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{where}: {key} must be a number or null")
    return float(value)


def _result_row(data: Mapping[str, object], where: str) -> ResultRow:
    return ResultRow(
        repo=_text(data, "repo", where),
        kind=_text(data, "kind", where),
        guard=_text(data, "guard", where),
        mode=_text(data, "mode", where),
        engine_model=_text(data, "engine_model", where),
        delivered=_flag(data, "delivered", where),
        idea_pipeline=_flag(data, "idea_pipeline", where),
        portfolio_rounds=_whole(data, "portfolio_rounds", where),
        generator_n=_whole(data, "generator_n", where),
        gain_pct=_number(data, "gain_pct", where),
        floor_pct=_number(data, "floor_pct", where),
        project_floor_pct=_number(data, "project_floor_pct", where),
    )


def read_results(path: Path) -> tuple[ResultRow, ...]:
    """``path``'s rows, strictly (the harness's own fields, one per library)."""
    rows: list[ResultRow] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        where = f"{path}:{number}"
        if not line.strip():
            continue
        try:
            data = strict_json(line)
        except ValueError as error:
            raise ValueError(f"{where}: {error}") from None
        if not isinstance(data, dict):
            raise ValueError(f"{where}: expected a JSON object")
        rows.append(_result_row(data, where))
    names = [row.repo for row in rows]
    if not rows or len(set(names)) != len(names):
        raise ValueError(f"{path}: expected one row per library, got {names}")
    return tuple(rows)


Files = list[tuple[Path, tuple[ResultRow, ...]]]


def _arm(paths: Sequence[Path], label: str) -> Files:
    """Each artifact's rows, refused unless wired with the arm's pipeline."""
    want = label == "P"
    found = [(path, read_results(path)) for path in paths]
    for path, rows in found:
        for row in rows:
            if row.idea_pipeline is not want:
                state = "on" if want else "off"
                raise ValueError(
                    f"{path}: {row.repo}: arm {label} must run with IDEA_PIPELINE {state}"
                )
            if row.mode != "wired":
                raise ValueError(f"{path}: {row.repo}: runs wired, not {row.mode!r}")
    return found


def _same(files: Files, key: str, want: object = None) -> None:
    """One value of ``key`` (``want`` when given, else the first run's) over
    every run of ``files``; a refusal names both sources."""
    first, (head, *_) = files[0]
    value, source = (
        (getattr(head, key), f"{first}: {head.repo}")
        if want is None
        else (want, "the rule")
    )
    for path, rows in files:
        for row in rows:
            if getattr(row, key) != value:
                raise ValueError(
                    f"{path}: {row.repo}: {key.upper()} {getattr(row, key)!r} "
                    f"differs from {value!r} ({source})"
                )


def paired_call(a: ResultRow, p: ResultRow) -> Call:
    """E2's form: P delivered and A did not, or both did and P's confirmed
    gain exceeds A's by more than the project floor (``c``); ``b`` the
    reverse. The project floor is the one each run judged its primary metric
    with (D41 c, D42), the larger of the two runs' (one library, two
    calibrations); with neither run's recorded (no baseline) no
    claim is made (``tie``). A breach on either side excludes the task."""
    if a.guard != "ok" or p.guard != "ok":
        return "excluded"
    if a.delivered != p.delivered:
        return "c" if p.delivered else "b"
    floors = [f for f in (a.project_floor_pct, p.project_floor_pct) if f is not None]
    if not a.delivered or a.gain_pct is None or p.gain_pct is None or not floors:
        return "tie"
    if p.gain_pct - a.gain_pct > max(floors):
        return "c"
    return "b" if a.gain_pct - p.gain_pct > max(floors) else "tie"


@dataclass(frozen=True)
class PairedTask:
    repo: str
    rep: int
    a: ResultRow | None
    p: ResultRow | None
    call: Call


@dataclass(frozen=True)
class FromResults:
    rule: Rule
    tasks: tuple[PairedTask, ...]
    false_wins_a: int | None  # None: no control results given for the arm
    false_wins_p: int | None
    control_runs: tuple[int, int]
    generator_n: tuple[int, int]  # GENERATOR_N of arm A and of arm P

    @property
    def b(self) -> int:
        return sum(t.call == "b" for t in self.tasks)

    @property
    def c(self) -> int:
        return sum(t.call == "c" for t in self.tasks)

    @property
    def met(self) -> bool | None:
        """E2's rule (``ab_decision`` and no P control false win); ``None``
        for E2c, or when either arm's controls are missing."""
        if self.rule == "e2c" or self.false_wins_a is None or self.false_wins_p is None:
            return None
        fair = ab_decision(self.b, self.c, self.false_wins_a, self.false_wins_p)
        return fair and self.false_wins_p == 0


def _false_wins(files: Files, given: bool) -> tuple[int | None, int]:
    """Delivered control runs (``None``: the arm's controls were not given)
    and the number of control runs."""
    controls = [r for _, rows in files for r in rows if r.kind == "control"]
    return (sum(r.delivered for r in controls) if given else None), len(controls)


def pair_results(
    arm_a: Sequence[Path],
    arm_p: Sequence[Path],
    *,
    controls_a: Sequence[Path] = (),
    controls_p: Sequence[Path] = (),
    rule: Rule = "e2",
) -> FromResults:
    """Arm A's and arm P's artifacts (one per repetition, in order) paired by
    (library, repetition), refused unless every run is wired with the arm's
    ``IDEA_PIPELINE``, one ``PORTFOLIO_ROUNDS``, one ``ENGINE_MODEL`` and
    one ``GENERATOR_N`` (E2c: arm A at ``E2C_GENERATOR_N``, arm P at one)."""
    if not arm_a or not arm_p:
        raise ValueError("pairing needs at least one artifact per arm")
    if rule == "e2c" and (controls_a or controls_p):
        raise ValueError("e2c takes no controls: its rule is c' - b' alone")
    a_files, p_files = _arm(arm_a, "A"), _arm(arm_p, "P")
    a_controls, p_controls = _arm(controls_a, "A"), _arm(controls_p, "P")
    every = [*a_files, *p_files, *a_controls, *p_controls]
    _same(every, "portfolio_rounds")
    _same(every, "engine_model")
    if rule == "e2":
        _same(every, "generator_n")
    else:
        _same(a_files, "generator_n", E2C_GENERATOR_N)
        _same(p_files, "generator_n")
    n_a, n_p = (files[0][1][0].generator_n for files in (a_files, p_files))
    tasks: list[PairedTask] = []
    for rep in range(1, max(len(a_files), len(p_files)) + 1):
        a = {r.repo: r for r in a_files[rep - 1][1]} if rep <= len(a_files) else {}
        p = {r.repo: r for r in p_files[rep - 1][1]} if rep <= len(p_files) else {}
        for repo in dict.fromkeys([*a, *p]):
            left, right = a.get(repo), p.get(repo)
            call: Call = "excluded"
            if left is not None and right is not None:
                call = paired_call(left, right)
            tasks.append(PairedTask(repo, rep, left, right, call))
    wins_a, runs_a = _false_wins([*a_files, *a_controls], bool(controls_a))
    wins_p, runs_p = _false_wins([*p_files, *p_controls], bool(controls_p))
    return FromResults(rule, tuple(tasks), wins_a, wins_p, (runs_a, runs_p), (n_a, n_p))


def _side(row: ResultRow | None) -> list[object]:
    if row is None:
        return ["-", "-"]
    return [flag(row.delivered), "-" if row.gain_pct is None else f"{row.gain_pct:.1f}"]


def _floor(task: PairedTask, key: str) -> str:
    floors = [getattr(r, key) for r in (task.a, task.p) if r is not None]
    found = [f for f in floors if f is not None]
    return f"{max(found):.1f}" if found else "-"


def _wins(wins: int | None, runs: int) -> str:
    return "not given" if wins is None else f"{wins}/{runs}"


def _verdict(found: FromResults) -> str:
    lead = found.c - found.b
    if found.rule == "e2c":
        reading = (
            "attributed to trial count: GENERATOR_N=10 and PORTFOLIO_ROUNDS=2 "
            "change for today's generator, the pipeline stays opt-in"
            if lead <= 1
            else "attributed to the ideas"
        )
        return f"E2c (P against the --arm-a runs): c' - b' = {lead}: {reading}."
    if found.met is None:
        return (
            f"c - b = {lead}; undecided: E2 needs both arms' control results "
            "(--controls-a, --controls-p)."
        )
    if found.met:
        return (
            f"c - b = {lead} and no P control false win: E2's rule is met "
            "(IDEA_PIPELINE=True, PORTFOLIO_ROUNDS=2 once N0c is in)."
        )
    return (
        f"c - b = {lead} (at least {MIN_DISCORDANT_LEAD} needed) with "
        f"{found.false_wins_p} P control false win(s) (none allowed): E2's rule "
        "is not met; the pipeline stays opt-in."
    )


def render_from_results(found: FromResults) -> str:
    """The paired tasks and the rule's reading, every cell sanitised."""
    lines = [
        "## E2 pairing from results",
        "",
        "| repo | rep | A delivered | A gain % | P delivered | P gain % "
        "| project floor % | combination floor % | call |",
        "| --- | ---: | --- | ---: | --- | ---: | ---: | ---: | --- |",
    ]
    for t in found.tasks:
        floors = [_floor(t, "project_floor_pct"), _floor(t, "floor_pct")]
        lines.append(cells([t.repo, t.rep, *_side(t.a), *_side(t.p), *floors, t.call]))
    paired = sum(t.call != "excluded" for t in found.tasks)
    runs_a, runs_p = found.control_runs
    lines += [
        "",
        f"Paired tasks: {paired} (excluded {len(found.tasks) - paired}: a guard "
        f"breach, or a library one arm never ran); discordant b = {found.b}, "
        f"c = {found.c}; exact two-sided McNemar p = "
        f"{mcnemar_exact(found.b, found.c):.4f}.",
        f"Control false wins: A {_wins(found.false_wins_a, runs_a)}, "
        f"P {_wins(found.false_wins_p, runs_p)}. GENERATOR_N: "
        f"A {found.generator_n[0]}, P {found.generator_n[1]}.",
        _verdict(found),
    ]
    return "\n".join(lines)


def from_results_main(
    argv: Sequence[str] | None = None, echo: Callable[[str], None] = print
) -> int:
    """``--from-results``: pair the artifacts and print the reading; 2 on an
    unreadable or refused artifact (argparse exits 2 on bad arguments)."""
    parser = argparse.ArgumentParser(prog="discovery_ab")
    parser.add_argument("--from-results", action="store_true", required=True)
    parser.add_argument("--arm-a", nargs="+", type=Path, required=True)
    parser.add_argument("--arm-p", nargs="+", type=Path, required=True)
    parser.add_argument("--controls-a", nargs="+", type=Path, default=[])
    parser.add_argument("--controls-p", nargs="+", type=Path, default=[])
    parser.add_argument("--rule", choices=("e2", "e2c"), default="e2")
    args = parser.parse_args(argv)
    try:
        found = pair_results(
            args.arm_a,
            args.arm_p,
            controls_a=args.controls_a,
            controls_p=args.controls_p,
            rule=args.rule,
        )
    except (OSError, ValueError) as error:
        echo(f"error: {error}")
        return 2
    for line in render_from_results(found).splitlines():
        echo(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(from_results_main())
