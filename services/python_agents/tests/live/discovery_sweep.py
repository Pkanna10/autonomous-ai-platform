"""E3, the blind hypothesis sweep: which model and effort find the root cause?

For every repository of the benchmark corpus (12 slowdowns, 3 controls)
and the hard corpus (10), phase 1 (``discovery.phase_one``) runs once and
its facts are shared by every arm, so the arms differ only in generation.
Each arm (``ARMS``, or ``$LIVE_SWEEP_ARMS``) calls ``generate_hypotheses``
(n = 5, no techniques: blind) through a transport whose chain is the arm's
model alone; Fable 5.1 at medium joins on the 12 benchmark slowdowns when
``$LIVE_SWEEP_FABLE=1`` (the research plan's optional arm), in a run of its
own (its worst case is about 1.17 USD, with a cap of 1.40 USD).

Budget: one ``LiveRun`` per repository shared by phase 1, the arms and the
graders, capped at ``SweepPlan.cap_for(repo)``: the sum of the worst cases
of every request it may send (phase 1, each arm at ``BLIND_PROMPT_BOUND``
and 16000 output tokens, each grader on a slowdown), rounded up. No
request can be refused for the budget, so no arm loses its data because an
earlier one spent much. The Fable run and the cache probe are capped the
same way.

Recorded per (repository, arm), never asserted: hit@1 and hit@5 (the
grader, ``discovery_grader``; an ungraded row counts in no rate and is
reported apart), the root causes its hypotheses target, the number of
hypotheses, the generation
and grader cost, tokens (input, output, thinking, cache reads), wall
seconds; for a control, whether any hypothesis claims a gain of at least
``BIG_GAIN``. The cache probe (``cache_probe``) generates twice with the
shipped playbook on one model and effort and records the second call's
``cache_read_input_tokens`` (expected > 0: the playbook rides in the cached
system block, ``research.playbook.research_system``).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Final

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.common.models import (
    METRIC_WALL_TIME_S,
    Direction,
    Objective,
    ObjectiveKind,
)
from autonomous_ai_agents.optimization.generate import GENERATE_MAX_TOKENS
from autonomous_ai_agents.research.playbook import load_playbook

from .conftest import LiveRun
from .corpus import CORPUS, HARD_CORPUS, MIN_FIX_GAIN, CorpusRepo
from .discovery import (
    BLIND_PROMPT_BOUND,
    FABLE,
    OPUS,
    PHASE_ONE_WORST_USD,
    PROBE_PROMPT_BOUND,
    SONNET,
    Arm,
    ArmResult,
    RepoFacts,
    ceil_usd,
    generate_arm,
    worst_usd,
)
from .discovery_grader import GRADE_WORST_USD, Grade, ReferencePatch, grade
from .discovery_io import (
    ResultsSink,
    cells,
    env_flag,
    flag,
    per,
    rate,
    write_markdown,
)

ARMS_ENV: Final = "LIVE_SWEEP_ARMS"
FABLE_ENV: Final = "LIVE_SWEEP_FABLE"
ARMS: Final = (
    Arm("opus-5-5-low", OPUS, "low"),
    Arm("opus-5-5-medium", OPUS, "medium"),
    Arm("opus-5-5-high", OPUS, "high"),
    Arm("sonnet-5-5-medium", SONNET, "medium"),
    Arm("sonnet-5-5-high", SONNET, "high"),
)
FABLE_ARM: Final = Arm("fable-5-1-medium", FABLE, "medium")
SWEEP_N: Final = 5
PROBE_ARM: Final = Arm("sonnet-5-5-medium", SONNET, "medium")


def arm_worst_usd(arm: Arm) -> float:
    """One blind generation's worst case (the shipped 16000 output tokens)."""
    return worst_usd(BLIND_PROMPT_BOUND, GENERATE_MAX_TOKENS, arm.model)


FABLE_RUN_CAP_USD: Final = ceil_usd(arm_worst_usd(FABLE_ARM) + GRADE_WORST_USD)
CACHE_PROBE_CAP_USD: Final = ceil_usd(
    2 * worst_usd(PROBE_PROMPT_BOUND, GENERATE_MAX_TOKENS, PROBE_ARM.model)
)
SWEEP_REPOS: Final = (*CORPUS, *HARD_CORPUS)
FABLE_REPOS: Final = tuple(r for r in CORPUS if r.kind == "slowdown")
BIG_GAIN: Final = MIN_FIX_GAIN  # a control's "big gain" claim: the 30 % fix bar


def sweep_arms(environ: Mapping[str, str]) -> tuple[Arm, ...]:
    """``$LIVE_SWEEP_ARMS``: unset is every arm; else comma-separated arm
    labels, each exactly one of ``ARMS``, none repeated."""
    if ARMS_ENV not in environ:
        return ARMS
    known = {arm.label: arm for arm in ARMS}
    labels = environ[ARMS_ENV].split(",")
    if any(x not in known for x in labels) or len(set(labels)) != len(labels):
        raise ValueError(
            f"{ARMS_ENV} must list distinct arms out of {', '.join(known)}, "
            f"got {environ[ARMS_ENV]!r}"
        )
    return tuple(known[label] for label in labels)


@dataclass(frozen=True)
class SweepPlan:
    arms: tuple[Arm, ...]
    fable: bool

    def cap_for(self, repo: CorpusRepo) -> float:
        """The repository's run: phase 1, every arm, a grader per arm on a
        slowdown, each at its worst case, rounded up."""
        total = PHASE_ONE_WORST_USD + math.fsum(arm_worst_usd(a) for a in self.arms)
        if repo.kind != "control":
            total += len(self.arms) * GRADE_WORST_USD
        return ceil_usd(total)


def sweep_plan(environ: Mapping[str, str]) -> SweepPlan:
    """Every knob, validated strictly (in the module fixture, before any spend)."""
    return SweepPlan(arms=sweep_arms(environ), fable=env_flag(environ, FABLE_ENV))


def sweep_need(plan: SweepPlan) -> float:
    """The sum of the caps the suite asks the ledger for."""
    fable = len(FABLE_REPOS) * FABLE_RUN_CAP_USD if plan.fable else 0.0
    repos = math.fsum(plan.cap_for(repo) for repo in SWEEP_REPOS)
    return repos + CACHE_PROBE_CAP_USD + fable


def grade_arm(
    run: LiveRun,
    budget: Budget,
    repo: CorpusRepo,
    patches: Sequence[ReferencePatch],
    result: ArmResult,
    *,
    base: Settings = settings,
) -> Grade | None:
    """The arm's grade; ``None`` for a control (no fix to grade against)."""
    if not patches:
        return None
    return grade(run, budget, repo, patches, result.hypotheses, base=base)


@dataclass(frozen=True)
class SweepRow:
    """One (repository, arm) of the sweep (recorded, never asserted)."""

    repo: str
    kind: str
    category: str
    arm: str
    model: str
    effort: str
    n_hypotheses: int
    hit_at_1: bool | None  # None: a control, or the grader failed
    hit_at_5: bool | None
    root_causes_hit: tuple[int, ...]  # the reference parts some idea targets
    root_causes: int  # how many parts the grader was shown (0: not graded)
    big_gain_claim: bool | None  # controls only
    generation_cost_usd: float
    grader_cost_usd: float
    input_tokens: int
    output_tokens: int
    thinking_tokens: int | None
    cache_read_tokens: int
    wall_s: float
    served_models: tuple[str, ...]
    phase_one_cost_usd: float
    error: str | None
    grader_error: str | None

    def record(self) -> dict[str, object]:
        return {"experiment": "E3-sweep", **asdict(self)}


def sweep_row(
    repo: CorpusRepo, result: ArmResult, graded: Grade | None, phase_cost: float
) -> SweepRow:
    claim = None
    if repo.kind == "control":
        claim = any(h.expected_gain >= BIG_GAIN for h in result.hypotheses)
    return SweepRow(
        repo=repo.name,
        kind=repo.kind,
        category=repo.category,
        arm=result.arm.label,
        model=result.arm.model,
        effort=result.arm.effort,
        n_hypotheses=len(result.hypotheses),
        hit_at_1=None if graded is None else graded.hit_at(1),
        hit_at_5=None if graded is None else graded.hit_at(SWEEP_N),
        root_causes_hit=()
        if graded is None or graded.error is not None
        else tuple(sorted({c for c in graded.causes if c is not None})),
        root_causes=0 if graded is None else graded.parts,
        big_gain_claim=claim,
        generation_cost_usd=result.cost_usd,
        grader_cost_usd=0.0 if graded is None else graded.cost_usd,
        input_tokens=result.tokens("input_tokens"),
        output_tokens=result.tokens("output_tokens"),
        thinking_tokens=result.thinking_tokens,
        cache_read_tokens=result.tokens("cache_read_tokens"),
        wall_s=round(result.wall_s, 3),
        served_models=result.models,
        phase_one_cost_usd=phase_cost,
        error=result.error,
        grader_error=None if graded is None else graded.error,
    )


@dataclass(frozen=True)
class Probe:
    """The cache probe: the same playbook twice on one model and effort."""

    model: str
    effort: str
    first_cache_write: int
    second_cache_read: int
    cost_usd: float
    answered: bool
    error: str | None

    @property
    def hit(self) -> bool:
        return self.second_cache_read > 0

    def record(self) -> dict[str, object]:
        return {"experiment": "E3-cache-probe", "hit": self.hit, **asdict(self)}


def cache_probe(run: LiveRun, repo: CorpusRepo, *, base: Settings = settings) -> Probe:
    """Two generator calls with the whole shipped playbook; no repository
    is read or run (the facts are the project's name and an objective)."""
    project = repo.project(repo.path)
    objective = Objective(
        project_id=project.id,
        kind=ObjectiveKind.runtime,
        metric=METRIC_WALL_TIME_S,
        direction=Direction.minimize,
        min_relative_gain=base.MIN_RELATIVE_GAIN,
        description="minimize wall time",
    )
    facts = RepoFacts(project, None, (), objective)
    budget = Budget(run.cap_usd)
    playbook = load_playbook()
    calls = [
        generate_arm(PROBE_ARM, run, budget, facts, n=3, techniques=playbook, base=base)
        for _ in range(2)
    ]
    usages = [u for call in calls for u in call.usages]
    errors = [c.error for c in calls if c.error is not None]
    return Probe(
        model=PROBE_ARM.model,
        effort=PROBE_ARM.effort,
        first_cache_write=usages[0].cache_write_tokens if usages else 0,
        second_cache_read=usages[1].cache_read_tokens if len(usages) > 1 else 0,
        cost_usd=math.fsum(c.cost_usd for c in calls),
        answered=len(usages) == 2,
        error="; ".join(errors) or None,
    )


def _arm_line(label: str, rows: Sequence[SweepRow]) -> list[object]:
    slow = [r for r in rows if r.kind != "control"]
    graded = [r for r in slow if r.hit_at_5 is not None]
    controls = [r for r in rows if r.kind == "control"]
    hits1 = sum(r.hit_at_1 is True for r in graded)
    hits5 = sum(r.hit_at_5 is True for r in graded)
    spend = math.fsum(r.generation_cost_usd for r in rows)
    slow_spend = math.fsum(r.generation_cost_usd for r in graded)
    claims = sum(r.big_gain_claim is True for r in controls)
    return [
        label,
        rate(hits1, len(graded)),
        rate(hits5, len(graded)),
        per(spend, len(rows)),
        per(slow_spend, hits5),
        rate(claims, len(controls)),
        len(slow) - len(graded),
    ]


def _causes(row: SweepRow) -> str:
    if not row.root_causes:
        return "-"
    hit = ", ".join(str(c) for c in row.root_causes_hit) or "none"
    return f"{hit} of {row.root_causes}"


def render_sweep(rows: Sequence[SweepRow], probes: Sequence[Probe]) -> str:
    """The sweep summary: one row per (repository, arm), then per arm."""
    lines = ["## Blind hypothesis sweep (E3)", ""]
    if rows:
        lines += [
            "| repo | kind | arm | hypotheses | hit at 1 | hit at 5 | root causes "
            "| big gain claim | generation USD | grader USD | output | thinking "
            "| cache read | wall s | error |",
            "| --- | --- | --- | ---: | --- | --- | --- | --- | ---: | ---: | ---: "
            "| ---: | ---: | ---: | --- |",
        ]
        for r in rows:
            lines.append(
                cells(
                    [
                        r.repo,
                        r.kind,
                        r.arm,
                        r.n_hypotheses,
                        flag(r.hit_at_1),
                        flag(r.hit_at_5),
                        _causes(r),
                        flag(r.big_gain_claim),
                        f"{r.generation_cost_usd:.4f}",
                        f"{r.grader_cost_usd:.4f}",
                        r.output_tokens,
                        "-" if r.thinking_tokens is None else r.thinking_tokens,
                        r.cache_read_tokens,
                        f"{r.wall_s:.1f}",
                        r.error or r.grader_error or "-",
                    ]
                )
            )
        lines += [
            "",
            "| arm | hit at 1 rate | hit at 5 rate | cost per repo USD | cost per hit "
            "USD (graded slowdown spend / hits at 5) | control big-gain claims "
            "| ungraded slowdowns |",
            "| --- | --- | --- | ---: | ---: | --- | ---: |",
        ]
        for label in dict.fromkeys(r.arm for r in rows):
            lines.append(cells(_arm_line(label, [r for r in rows if r.arm == label])))
    else:
        lines.append("No sweep repository finished.")
    for probe in probes:
        lines += [
            "",
            cells(
                [
                    f"Cache probe {probe.model} {probe.effort}: first write "
                    f"{probe.first_cache_write}, second read "
                    f"{probe.second_cache_read} tokens, cache hit: "
                    f"{flag(probe.hit)}, {probe.cost_usd:.4f} USD"
                    + (f", {probe.error}" if probe.error else "")
                ]
            ),
        ]
    return "\n".join(lines)


@dataclass
class SweepRecorder:
    """The module's rows and probes; ``finish`` writes the summary once."""

    plan: SweepPlan
    sink: ResultsSink
    rows: list[SweepRow] = field(default_factory=list)
    probes: list[Probe] = field(default_factory=list)

    def record(self, rows: Sequence[SweepRow], run: LiveRun) -> None:
        for row in rows:
            self.rows.append(row)
            self.sink.write(row.record())
            run.note(
                f"sweep {row.repo} {row.arm}: {row.n_hypotheses} hypotheses, "
                f"hit@1 {flag(row.hit_at_1)}, hit@5 {flag(row.hit_at_5)}"
            )

    def record_probe(self, probe: Probe, run: LiveRun) -> None:
        self.probes.append(probe)
        self.sink.write(probe.record())
        run.note(f"cache probe: second read {probe.second_cache_read} tokens")

    def finish(self, echo: Callable[[str], None]) -> None:
        if self.rows or self.probes:
            text = render_sweep(self.rows, self.probes)
            write_markdown("Blind hypothesis sweep", text, self.sink.environ, echo)
