"""E5 on real code: the OSS discovery A/B (the product's key metric).

The E5 A/B on the synthetic corpora saturated (blind 44/44, playbook-matched
41/44); hand-aimed hypotheses on the OSS corpus (``oss.py``, 10 pinned
libraries) delivered 6/10 with gains of 3-14 % (run 40061541473). This
suite asks the same question where blind generation does not saturate, and
searches wide: how the win rate grows with the number of ideas tried.

Per library (``$LIVE_OSS_AB_REPOS``, default the whole ``oss.OSS_CORPUS``;
it may also name libraries of the second set, ``oss_v2.OSS_CORPUS_V2``,
for the technique-list re-test, see ``OSS_SELECTABLE``) and repetition
(``$LIVE_OSS_AB_REPS``, default 2, at most ``OSS_AB_MAX_REPS``), one task:

1. Phase 1 on a fresh clone: ``start_oss_loop`` with zero candidates (as
   ``discovery.phase_one`` does for a corpus repository): connect,
   understand, baseline and profile, every corpus guard, the facts read
   from its state. It is the first spend of the task's generation run.
2. Each selected arm (``$LIVE_OSS_AB_ARMS``, a comma list of a, b and c,
   default a,b) generates ``$LIVE_OSS_AB_N`` hypotheses (default and at
   most 10, at least ``discovery_ab.AB_N``) from those facts in the same
   run: A blind Sonnet 5.5 medium, B playbook-matched Sonnet 5.5 medium
   (``AB_K`` cards over the shipped playbook, as
   ``discovery_ab.retrieval_arm``), C blind Opus 5.5 low (off by default: it
   added no hit in the sweep and claimed gains on controls). Each bills its
   own model only (``check_calls``) and the clone is left untouched.
3. Each arm's efficiency hypotheses (``carry``: ``hotspot_ids`` cleared)
   run through one whole engine loop on a fresh clone, ``start_oss_loop``
   with those candidates and ``max_hypotheses_per_round`` set to their
   count: every one is trialled in the loop's single round (the router
   ends a run after the first round with a keep, and a round of the
   default 3 would stop the search there). An arm with no efficiency
   hypothesis runs no loop and counts as a loss.

Every loop, phase 1 included, runs ``ENGINE_MODEL`` Sonnet 5.5 without
fallbacks (``discovery_ab.ab_settings``). ``start_oss_loop`` and the factory
read the global settings, so ``engine_settings`` sets exactly those two
fields on them for the task and restores them after.

Caps, sums of worst cases: the generation run's cap is phase 1's understand
request and every selected arm's requests at their worst, rounded up to
0.05 USD (``gen_cap_usd``); ten ideas need more output than three, so the
generator gets ``GENERATE_MAX_TOKENS`` above ``AB_N`` (``generate_max_tokens``).
A whole loop has no prompt bound (the editor's conversation grows), so its
worst case is U24's: ``OSS_RUN_CAP_USD`` for the manifest's two trials,
``OSS_TRIAL_CAP_USD`` a trial (``$LIVE_OSS_AB_TRIAL_CAP_USD`` lowers it),
scaled with the trials the loop runs (``OssAbPlan.loop_cap``). The corpus's
prompt bounds were measured on small repositories and do not hold on OSS
clones (longer paths, fuller files), so this suite has its own
(``OSS_*_PROMPT_BOUND``), measured offline in ``test_discovery_oss_guards``
on the widest facts the engine lets any clone produce: the understander's
request is capped by ``ReadLimits`` whatever the repository, and the
generator's and matcher's by 30 hotspots on paths of at most
``OSS_MAX_PATH_CHARS`` characters (the assumption a ``LIVE_OSS_NETWORK=1``
case checks on every pinned clone) with symbols at the profiler's cap.
Non-ASCII text can still exceed a bound when the count endpoint fails and
the byte bound applies; then the request is refused before it is sent and
the task fails its guard, never billed past the cap. ``oss_ab_need`` is the
suite total; a plan past live-smoke's 150 USD ceiling is refused in the
module fixture: the default plan needs about 1026 USD, one library about
103 (of either set: the need depends on the counts, not the library), so
the Lead dispatches one library (or a few, at a lower trial cap) at a time.

Recorded, never asserted, per (library, repetition, arm): delivered, the
kept titles, the primary metric's gain, generation and loop cost, the guard
(one ``discovery_ab.AbRow`` as a JSON line to ``$LIVE_RESULTS_PATH``,
experiment ``E5-oss-ab``, and a cost-table note); per generated idea, in
the generator's rank order: title, class, verdict, gain and noise floor
(``RankRow``, experiment ``E5-oss-ab-rank``). The summary per arm (win rate,
mean gain over wins, cost per win over the rows whose guards held), win@k
(rendered "win in top k": GitHub reads an ``@`` as a mention)
for k in 1, 3, 5, 10 (the loop kept at least one of the first k ideas: one
k = 10 run gives the whole curve, since every idea is judged against the
same baseline), and, against A, the discordant counts and the exact
two-sided McNemar p for B and for C over the tasks whose two runs held
every guard (``discovery_ab.discordant``), go to the job summary and the
log, and after every task to three cost-table notes (the log's
module-teardown echo can be cut; the notes reach it whole).
"""

from __future__ import annotations

import ast
import functools
import math
import statistics
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Final

from e2e.conftest import Isolation, git

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.transport import LLMTransport
from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.common.models import (
    ChangeClass,
    Hypothesis,
    Project,
    Technique,
    Trial,
    Verdict,
    VerdictOutcome,
)
from autonomous_ai_agents.optimization.generate import (
    GENERATE_MAX_TOKENS,
    generate_hypotheses,
)
from autonomous_ai_agents.optimization.judges import primary_metric
from autonomous_ai_agents.orchestrator.main import EngineRunResult
from autonomous_ai_agents.research.playbook import (
    MATCH_MAX_TOKENS,
    TechniqueMatch,
    load_playbook,
    match_techniques,
)

from .conftest import LiveRun, StartLive
from .corpus import CorpusOutcome, Loop, check_loop_guards
from .discovery import (
    OPUS,
    PHASE_ONE_MODEL,
    Arm,
    ArmResult,
    PhaseOne,
    RepoFacts,
    carry,
    ceil_usd,
    check_calls,
    check_untouched,
    generate_arm,
    read_phase_one,
    run_arm,
    run_engine,
    worst_usd,
)
from .discovery_ab import (
    AB_ARM,
    AB_GENERATE_MAX_TOKENS,
    AB_K,
    AB_N,
    AbRow,
    Pairs,
    ab_row,
    ab_settings,
    discordant,
    excluded_tasks,
    mcnemar_exact,
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
from .oss import (
    OSS_CORPUS,
    OSS_RUN_CAP_USD,
    PRODUCTION,
    GitPolicy,
    OssRepo,
    start_oss_loop,
)
from .oss_v2 import OSS_CORPUS_V2

REPS_ENV: Final = "LIVE_OSS_AB_REPS"
ARMS_ENV: Final = "LIVE_OSS_AB_ARMS"
N_ENV: Final = "LIVE_OSS_AB_N"
TRIAL_CAP_ENV: Final = "LIVE_OSS_AB_TRIAL_CAP_USD"
REPOS_ENV: Final = "LIVE_OSS_AB_REPOS"
OSS_AB_REPS: Final = 2
OSS_AB_MAX_REPS: Final = 3
OSS_AB_N: Final = 10
OSS_AB_MAX_N: Final = 10
OSS_MANIFEST_TRIALS: Final = 2  # the manifest's two hypotheses a U24 run
OSS_TRIAL_CAP_USD: Final = OSS_RUN_CAP_USD / OSS_MANIFEST_TRIALS
WIN_AT: Final = (1, 3, 5, 10)
CAP_CEILING_USD: Final = 150.0  # live-smoke's suite_cap_usd ceiling
OSS_EXPERIMENT: Final = "E5-oss-ab"
RANK_EXPERIMENT: Final = "E5-oss-ab-rank"
AIMED_CONTEXT: Final = "aimed hypotheses, run 40061541473: 6/10 delivered"
OPUS_LOW: Final = Arm("opus-5-5-low", OPUS, "low")
ENGINE_FIELDS: Final = ("ENGINE_MODEL", "ENGINE_FALLBACKS")
NOTE_CHARS: Final = 200  # the cost table's cell
NO_LOOP: Final = frozenset({"no_hypotheses", "not_run"})  # a row whose loop never ran
NOT_HANDED: Final = "not_handed"  # behaviour or novel: never a candidate
NOT_TRIALLED: Final = "not_trialled"  # handed over, no trial (a budget stop)
NO_RESULT: Final = "no_result"  # no loop ran, or it raised before a state
NO_VERDICT: Final = "no_verdict"  # trialled, but the run ended before its verdict

# What ``call()`` may count, in tokens, for each request on any OSS clone
# (the byte bound plus the allowance), measured in test_discovery_oss_guards.
OSS_MAX_PATH_CHARS: Final = 200  # every tracked path of a pinned clone
OSS_UNDERSTAND_PROMPT_BOUND: Final = 114_000  # every ReadLimits cap reached
OSS_BLIND_PROMPT_BOUND: Final = 41_000  # generator, no techniques
OSS_CARDS_PROMPT_BOUND: Final = 48_000  # generator with the 3 largest cards
OSS_MATCH_PROMPT_BOUND: Final = 100_000  # matcher with the whole playbook
OSS_PHASE_ONE_WORST_USD: Final = worst_usd(
    OSS_UNDERSTAND_PROMPT_BOUND, settings.UNDERSTAND_MAX_TOKENS, PHASE_ONE_MODEL
)
OSS_PHASE_ONE_CAP_USD: Final = ceil_usd(OSS_PHASE_ONE_WORST_USD)


def selectable(*sets: Sequence[OssRepo]) -> tuple[OssRepo, ...]:
    """The libraries ``$LIVE_OSS_AB_REPOS`` may name, in set order; a name
    in two sets is refused (a name must pick one library)."""
    repos = tuple(repo for group in sets for repo in group)
    names = [repo.name for repo in repos]
    shared = sorted({name for name in names if names.count(name) > 1})
    if shared:
        raise ValueError(f"the OSS library sets share a name: {', '.join(shared)}")
    return repos


# The first set, then the second (the technique-list re-test); the default
# plan stays the first set alone, so its guards and notes are unchanged.
OSS_SELECTABLE: Final = selectable(OSS_CORPUS, OSS_CORPUS_V2)

# ---------------------------------------------------------------------------
# Arms, caps and the plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OssArm:
    """One arm: what ``$LIVE_OSS_AB_ARMS`` names, its row label, its setting."""

    key: str  # a, b or c
    label: str  # A, B or C
    setting: Arm
    retrieval: bool  # B: match playbook cards first, generate from them


ARM_A: Final = OssArm("a", "A", AB_ARM, retrieval=False)
ARM_B: Final = OssArm("b", "B", AB_ARM, retrieval=True)
ARM_C: Final = OssArm("c", "C", OPUS_LOW, retrieval=False)
OSS_ARMS: Final = (ARM_A, ARM_B, ARM_C)
DEFAULT_ARMS: Final = (ARM_A, ARM_B)


def generate_max_tokens(n: int) -> int:
    """The generation ``max_tokens`` of both arms: E5's 8000 for its
    ``AB_N`` ideas, the generator's default above that."""
    return AB_GENERATE_MAX_TOKENS if n <= AB_N else GENERATE_MAX_TOKENS


def arm_worst_usd(arm: OssArm, n: int) -> float:
    """The worst case of the arm's requests on the OSS bounds."""
    model, tokens = arm.setting.model, generate_max_tokens(n)
    if arm.retrieval:
        return worst_usd(OSS_MATCH_PROMPT_BOUND, MATCH_MAX_TOKENS, model) + worst_usd(
            OSS_CARDS_PROMPT_BOUND, tokens, model
        )
    return worst_usd(OSS_BLIND_PROMPT_BOUND, tokens, model)


def gen_cap_usd(arms: Sequence[OssArm], n: int) -> float:
    """The generation run's cap: phase 1 and every arm at its worst."""
    worst = math.fsum(arm_worst_usd(arm, n) for arm in arms)
    return ceil_usd(OSS_PHASE_ONE_WORST_USD + worst)


@dataclass(frozen=True)
class OssAbPlan:
    reps: int
    arms: tuple[OssArm, ...]
    n: int
    trial_cap: float
    repos: tuple[OssRepo, ...] = OSS_CORPUS

    def loop_cap(self, trials: int) -> float:
        """A loop's cap: the per-trial worst case times the trials it runs."""
        if trials < 1:
            raise ValueError(f"a loop runs at least one trial, got {trials}")
        return ceil_usd(trials * self.trial_cap)


def _keys(
    environ: Mapping[str, str], name: str, known: Sequence[str]
) -> tuple[str, ...] | None:
    """Distinct members of ``known``, comma separated, in ``known``'s order;
    ``None`` when unset."""
    if name not in environ:
        return None
    raw = environ[name]
    keys = raw.split(",")
    if not set(keys) <= set(known) or len(set(keys)) != len(keys):
        raise ValueError(
            f"{name} must name distinct entries of {', '.join(known)} separated "
            f"by commas, got {raw!r}"
        )
    return tuple(key for key in known if key in keys)


def oss_ab_arms(environ: Mapping[str, str]) -> tuple[OssArm, ...]:
    """``$LIVE_OSS_AB_ARMS``: distinct keys of a, b and c, comma separated,
    in the canonical order; unset means a and b (C is opt-in)."""
    keys = _keys(environ, ARMS_ENV, [arm.key for arm in OSS_ARMS])
    if keys is None:
        return DEFAULT_ARMS
    return tuple(arm for arm in OSS_ARMS if arm.key in keys)


def oss_ab_repos(environ: Mapping[str, str]) -> tuple[OssRepo, ...]:
    """``$LIVE_OSS_AB_REPOS``: distinct names of ``OSS_SELECTABLE`` (the
    first set or the second), comma separated, in its order; unset means
    every library of the first set."""
    names = _keys(environ, REPOS_ENV, [repo.name for repo in OSS_SELECTABLE])
    if names is None:
        return OSS_CORPUS
    return tuple(repo for repo in OSS_SELECTABLE if repo.name in names)


def oss_ab_need(plan: OssAbPlan) -> float:
    """The sum of the caps the suite asks the ledger for: per task the
    generation run plus one loop of ``n`` trials per arm (an arm hands over
    at most its ``n`` ideas)."""
    per_task = gen_cap_usd(plan.arms, plan.n) + len(plan.arms) * plan.loop_cap(plan.n)
    return plan.reps * len(plan.repos) * per_task


def oss_ab_plan(environ: Mapping[str, str]) -> OssAbPlan:
    """Every knob, validated strictly, and a plan past the ceiling refused
    (in the module fixture, before any spend)."""
    plan = OssAbPlan(
        reps=env_whole(environ, REPS_ENV, OSS_AB_REPS, low=1, high=OSS_AB_MAX_REPS),
        arms=oss_ab_arms(environ),
        n=env_whole(environ, N_ENV, OSS_AB_N, low=AB_N, high=OSS_AB_MAX_N),
        trial_cap=env_number(
            environ, TRIAL_CAP_ENV, OSS_TRIAL_CAP_USD, high=OSS_TRIAL_CAP_USD
        ),
        repos=oss_ab_repos(environ),
    )
    need = oss_ab_need(plan)
    if need > CAP_CEILING_USD:
        raise ValueError(
            f"{len(plan.repos)} libraries x {plan.reps} reps x arms "
            f"{','.join(a.key for a in plan.arms)} at {N_ENV}={plan.n} and "
            f"{TRIAL_CAP_ENV}={plan.trial_cap:g} need {need:.2f} USD, past the "
            f"{CAP_CEILING_USD:g} USD ceiling of a live-smoke dispatch: name fewer "
            f"libraries in {REPOS_ENV} or arms in {ARMS_ENV}, or lower "
            f"{TRIAL_CAP_ENV}, {N_ENV} or {REPS_ENV}"
        )
    return plan


# ---------------------------------------------------------------------------
# The engine's settings, phase 1, the arms and their loops
# ---------------------------------------------------------------------------


@contextmanager
def engine_settings(cfg: Settings) -> Iterator[None]:
    """The global settings with ``cfg``'s engine model and fallbacks for the
    block, restored after (``start_oss_loop`` and the factory read the
    global: its chain, editor and trial budget follow)."""
    saved = {name: getattr(settings, name) for name in ENGINE_FIELDS}
    try:
        for name in ENGINE_FIELDS:
            setattr(settings, name, getattr(cfg, name))
        yield
    finally:
        for name, value in saved.items():
            setattr(settings, name, value)


def no_candidates(project: Project) -> tuple[Hypothesis, ...]:
    return ()


def start_oss_phase_one(
    repo: OssRepo,
    run: LiveRun,
    root: Path,
    isolation: Isolation,
    *,
    policy: GitPolicy = PRODUCTION,
) -> Loop:
    """``repo`` cloned under ``root`` and wired with zero candidates."""
    root.mkdir(parents=True, exist_ok=True)
    loop = start_oss_loop(
        repo, run, root, isolation, policy=policy, candidates=no_candidates
    )
    return replace(loop, cap_usd=min(OSS_PHASE_ONE_CAP_USD, run.cap_usd), mode="blind")


def oss_phase_one(
    repo: OssRepo,
    run: LiveRun,
    root: Path,
    isolation: Isolation,
    *,
    policy: GitPolicy = PRODUCTION,
) -> PhaseOne:
    """Phase 1 as the run's first spend, with every corpus guard."""
    if run.records:
        raise ValueError("phase one must be the first spend of its run")
    loop = start_oss_phase_one(repo, run, root, isolation, policy=policy)
    result = loop.run()
    check_loop_guards(loop, run, result, isolation)
    return read_phase_one(loop, run, result)


def matched_arm(
    run: LiveRun,
    budget: Budget,
    facts: RepoFacts,
    *,
    playbook: Sequence[Technique],
    n: int,
    base: Settings = settings,
) -> ArmResult:
    """Arm B with ``n`` ideas: ``discovery_ab.retrieval_arm``'s recipe (match
    ``AB_K`` cards, generate from the matched cards only), whose ``n`` is
    fixed at ``AB_N`` there."""

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
        found = generate_hypotheses(
            transport,
            budget,
            project=facts.project,
            understanding=facts.understanding,
            hotspots=facts.hotspots,
            objective=facts.objective,
            techniques=[by_slug[m.slug] for m in matches if m.slug in by_slug],
            n=n,
            effort=AB_ARM.effort,
            max_tokens=generate_max_tokens(n),
            notes=notes,
            config=cfg,
        )
        return found, matches

    return run_arm(AB_ARM, run, base, work)


def generate(
    arm: OssArm,
    run: LiveRun,
    budget: Budget,
    facts: RepoFacts,
    *,
    playbook: Sequence[Technique],
    n: int,
) -> ArmResult:
    """The arm's ``n`` hypotheses from phase 1's facts, in the generator's
    rank order."""
    if arm.retrieval:
        return matched_arm(run, budget, facts, playbook=playbook, n=n)
    return generate_arm(
        arm.setting, run, budget, facts, n=n, max_tokens=generate_max_tokens(n)
    )


def start_arm_loop(
    repo: OssRepo,
    run: LiveRun,
    root: Path,
    isolation: Isolation,
    candidates: Sequence[Hypothesis],
    *,
    policy: GitPolicy = PRODUCTION,
) -> Loop:
    """A fresh clone under ``root`` with ``candidates`` rebound to its
    project, every one trialled in the loop's first round."""
    if not candidates:
        raise ValueError("an arm loop needs at least one candidate")

    def rebound(project: Project) -> tuple[Hypothesis, ...]:
        return tuple(
            h.model_copy(update={"project_id": project.id}) for h in candidates
        )

    root.mkdir(parents=True, exist_ok=True)
    loop = start_oss_loop(repo, run, root, isolation, policy=policy, candidates=rebound)
    wide = replace(loop.context, max_hypotheses_per_round=len(candidates))
    return replace(loop, context=wide, mode="blind")


def clone_problems(path: Path) -> list[str]:
    """Why a clone could exceed the OSS bounds: a tracked path longer than
    ``OSS_MAX_PATH_CHARS`` or not printable ASCII, a non-ASCII function or
    class name in a tracked ``.py`` file (unparsable files are skipped)."""
    problems: list[str] = []
    for name in filter(None, git(path, "ls-files", "-z").split("\0")):
        if len(name) > OSS_MAX_PATH_CHARS or not (
            name.isascii() and name.isprintable()
        ):
            problems.append(
                f"{name}: a path of {len(name)} characters (at most "
                f"{OSS_MAX_PATH_CHARS}, printable ASCII)"
            )
            continue
        file = path / name
        if not name.endswith(".py") or file.is_symlink():
            continue
        try:
            tree = ast.parse(file.read_bytes())
        except (SyntaxError, ValueError):
            continue
        wide = sorted(
            {
                node.name
                for node in ast.walk(tree)
                if isinstance(
                    node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
                )
                and not node.name.isascii()
            }
        )
        if wide:
            problems.append(f"{name}: non-ASCII names {', '.join(wide)}")
    return problems


# ---------------------------------------------------------------------------
# Rank rows: every generated idea's fate, in the generator's order
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RankRow:
    """One generated idea of one (repo, rep, arm), at its generator rank."""

    repo: str
    rep: int
    arm: str
    rank: int  # 1 = the generator's first idea
    title: str
    change_class: str
    verdict: str  # a VerdictOutcome, or NOT_HANDED / NOT_TRIALLED / NO_RESULT
    gain_pct: float | None  # the verdict's gain
    noise_floor_pct: float | None  # the primary-metric judge's noise floor
    guard: str

    def record(self) -> dict[str, object]:
        return {"experiment": RANK_EXPERIMENT, **asdict(self)}


def _noise_floor(verdict: Verdict, metric: str | None) -> float | None:
    floors = [j for j in verdict.judge_results if j.noise_floor is not None]
    primary = [j for j in floors if j.metric == metric]
    return next((j.noise_floor for j in primary or floors), None)


def _pct(value: float | None) -> float | None:
    return None if value is None else 100 * value


def rank_rows(
    repo: str,
    rep: int,
    arm: str,
    hypotheses: Sequence[Hypothesis],
    result: EngineRunResult | None,
    *,
    guard: str,
) -> list[RankRow]:
    """Each generated hypothesis in rank order with what the loop made of it,
    matched by id (``carry`` and the rebinding keep it)."""
    verdicts: dict[str, Verdict] = {}
    trialled: set[str] = set()
    metric: str | None = None
    if result is not None:
        state = result.state
        metric = primary_metric(state["objectives"])
        trials: Sequence[Trial] = state["trials"]
        trialled = {t.hypothesis_id for t in trials}
        for v in state["verdicts"]:
            verdicts.setdefault(v.hypothesis_id, v)
    rows: list[RankRow] = []
    for rank, h in enumerate(hypotheses, start=1):
        found = verdicts.get(h.id)
        if h.change_class is not ChangeClass.efficiency:
            verdict = NOT_HANDED
        elif found is not None:
            verdict = found.outcome.value
        elif result is None:
            verdict = NO_RESULT
        else:
            verdict = NO_VERDICT if h.id in trialled else NOT_TRIALLED
        rows.append(
            RankRow(
                repo=repo,
                rep=rep,
                arm=arm,
                rank=rank,
                title=h.title,
                change_class=h.change_class.value,
                verdict=verdict,
                gain_pct=None if found is None else _pct(found.gain),
                noise_floor_pct=(
                    None if found is None else _pct(_noise_floor(found, metric))
                ),
                guard=guard,
            )
        )
    return rows


def kept_ranks(rows: Sequence[RankRow]) -> tuple[int, ...]:
    return tuple(r.rank for r in rows if r.verdict == VerdictOutcome.keep.value)


def win_at(rows: Sequence[RankRow], k: int) -> bool:
    """The loop kept at least one of the generator's first ``k`` ideas (all
    of them when it generated fewer)."""
    return any(rank <= k for rank in kept_ranks(rows))


def win_curve(
    rows: Sequence[AbRow], ranks: Sequence[RankRow], label: str
) -> dict[int, tuple[int, int]]:
    """win@k for each ``WIN_AT`` k: (wins, tasks) over arm ``label``'s tasks
    whose guards held (an arm with no efficiency idea is a held loss)."""
    tasks = [(r.repo, r.rep) for r in rows if r.arm == label and r.guard == "ok"]
    by_task: dict[tuple[str, int], list[RankRow]] = {}
    for r in ranks:
        if r.arm == label:
            by_task.setdefault((r.repo, r.rep), []).append(r)
    return {
        k: (sum(win_at(by_task.get(task, []), k) for task in tasks), len(tasks))
        for k in WIN_AT
    }


# ---------------------------------------------------------------------------
# Rows, notes and the summary
# ---------------------------------------------------------------------------


def oss_record(row: AbRow, arm: OssArm, phase_cost: float, n: int) -> dict[str, object]:
    return {
        **row.record(),
        "experiment": OSS_EXPERIMENT,
        "arm_setting": arm.setting.label,
        "retrieval": arm.retrieval,
        "phase_one_cost_usd": phase_cost,
        "n": n,
    }


def _gain(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}%"


def _fit(text: str, room: int) -> str:
    return text if len(text) <= room else text[: max(room - 1, 0)] + "…"


def run_note(row: AbRow, ranks: Sequence[int] = ()) -> str:
    """The row's cost-table note (``<generation>+<loop> USD``); the kept
    titles get what the cell leaves."""
    guard = "ok" if row.guard == "ok" else "breach"
    head = (
        f"OSS-AB {row.repo} rep {row.rep} arm {row.arm}: delivered {flag(row.win)}, "
        f"gain {_gain(row.gain_pct)}, keep ranks "
        f"{','.join(map(str, ranks)) or '-'}, kept "
    )
    tail = (
        f", {row.generation_cost_usd:.4f}+{row.engine_cost_usd:.4f} USD, guard {guard}"
    )
    kept = "; ".join(row.kept) or "none"
    return head + _fit(kept, NOTE_CHARS - len(head) - len(tail)) + tail


def versus(rows: Sequence[AbRow], label: str) -> tuple[Pairs, int, int, int]:
    """``discordant`` of arm ``label`` against A (its rows as B's), and the
    tasks it could not pair (a guard breach, or an arm that never ran)."""
    picked = [
        row if row.arm == "A" else replace(row, arm="B")
        for row in rows
        if row.arm in ("A", label)
    ]
    pairs, b, c = discordant(picked)
    return pairs, b, c, excluded_tasks(picked)


@dataclass(frozen=True)
class _ArmTotals:
    rows: int
    held: int
    wins: int
    mean_gain: float | None
    spend: float
    generation: float
    loops: tuple[float, ...]
    no_idea: int
    cap_hit: int

    @classmethod
    def of(cls, group: Sequence[AbRow]) -> _ArmTotals:
        held = [r for r in group if r.guard == "ok"]
        wins = [r for r in held if r.win]
        gains = [r.gain_pct for r in wins if r.gain_pct is not None]
        return cls(
            rows=len(group),
            held=len(held),
            wins=len(wins),
            mean_gain=statistics.fmean(gains) if gains else None,
            spend=math.fsum(r.generation_cost_usd + r.engine_cost_usd for r in held),
            generation=math.fsum(r.generation_cost_usd for r in group),
            loops=tuple(r.engine_cost_usd for r in group if r.status not in NO_LOOP),
            no_idea=sum(r.status == "no_hypotheses" for r in group),
            cap_hit=sum(
                bool(r.budget_exhausted or r.trial_budget_error) for r in group
            ),
        )


def _setting(label: str) -> str:
    return next(a.setting.label for a in OSS_ARMS if a.label == label)


def _labels(rows: Sequence[AbRow]) -> list[str]:
    return [a.label for a in OSS_ARMS if any(r.arm == a.label for r in rows)]


def _arms(rows: Sequence[AbRow]) -> dict[str, _ArmTotals]:
    return {
        label: _ArmTotals.of([r for r in rows if r.arm == label])
        for label in _labels(rows)
    }


def _paired_line(rows: Sequence[AbRow], label: str) -> str:
    pairs, b, c, excluded = versus(rows, label)
    if not pairs:
        return f"{label} vs A: no pairs (excluded {excluded} task(s); an arm not run here)."
    return (
        f"{label} vs A: {len(pairs)} paired task(s) (excluded {excluded}: a guard "
        f"breach, or an arm that never ran); discordant b = {b} (A won, {label} "
        f"lost), c = {c} (A lost, {label} won), c - b = {c - b}; exact two-sided "
        f"McNemar p = {mcnemar_exact(b, c):.4f}."
    )


def _num(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def render_oss_ab(rows: Sequence[AbRow], ranks: Sequence[RankRow] = ()) -> str:
    lines = ["## OSS discovery A/B (E5 on real code)", ""]
    if not rows:
        return "\n".join([*lines, "No OSS A/B task finished."])
    lines += [
        "| repo | rep | arm | status | delivered | gain % | kept | generation USD "
        "| loop USD | matched | cap hit | guards |",
        "| --- | ---: | --- | --- | --- | ---: | --- | ---: | ---: | --- | --- | --- |",
    ]
    for r in rows:
        cap = (
            "-"
            if r.budget_exhausted is None
            else flag(r.budget_exhausted or r.trial_budget_error)
        )
        lines.append(
            cells(
                [
                    r.repo,
                    r.rep,
                    r.arm,
                    r.status,
                    flag(r.win),
                    _num(r.gain_pct),
                    "; ".join(r.kept) or "-",
                    f"{r.generation_cost_usd:.4f}",
                    f"{r.engine_cost_usd:.4f}",
                    ", ".join(r.matched) or "-",
                    cap,
                    r.guard if r.generation_error is None else r.generation_error,
                ]
            )
        )
    lines += [
        "",
        "| arm | setting | wins (guards held) | mean gain % over wins "
        "| cost per win USD | generation USD a task | loop USD a run "
        "| no efficiency idea | cap hit | breaches |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for label, t in _arms(rows).items():
        loop = f"{statistics.fmean(t.loops):.4f}" if t.loops else "-"
        lines.append(
            cells(
                [
                    label,
                    _setting(label),
                    rate(t.wins, t.held),
                    _num(t.mean_gain),
                    per(t.spend, t.wins),
                    per(t.generation, t.rows),
                    loop,
                    t.no_idea,
                    t.cap_hit,
                    t.rows - t.held,
                ]
            )
        )
    ks = " | ".join(f"win in top {k}" for k in WIN_AT)
    lines += ["", f"| arm | {ks} |", "| --- |" + " --- |" * len(WIN_AT)]
    for label in _labels(rows):
        curve = win_curve(rows, ranks, label)
        lines.append(cells([label, *(rate(*curve[k]) for k in WIN_AT)]))
    if ranks:
        lines += [
            "",
            "| repo | rep | arm | rank | title | class | verdict | gain % "
            "| noise floor % |",
            "| --- | ---: | --- | ---: | --- | --- | --- | ---: | ---: |",
        ]
        lines += [
            cells(
                [
                    r.repo,
                    r.rep,
                    r.arm,
                    r.rank,
                    r.title,
                    r.change_class,
                    r.verdict,
                    _num(r.gain_pct),
                    _num(r.noise_floor_pct),
                ]
            )
            for r in ranks
        ]
    tasks = len({(r.repo, r.rep) for r in rows})
    lines += [
        "",
        f"Tasks: {tasks}. {_paired_line(rows, 'B')}",
        _paired_line(rows, "C"),
        "Win in top k: the loop kept at least one of the generator's first k "
        "ideas (every idea is trialled in one round against the same baseline).",
        f"Context: {AIMED_CONTEXT} (gains 3-14 %, the manifest's two hand-aimed "
        "hypotheses per library). Arms: A blind Sonnet 5.5 medium, B "
        "playbook-matched Sonnet 5.5 medium, C blind Opus 5.5 low; every loop "
        "Sonnet 5.5 without fallbacks. Arms or libraries dispatched separately "
        "get their own phase 1: pair their rows by (repo, rep) from the notes.",
    ]
    return "\n".join(lines)


def summary_notes(
    rows: Sequence[AbRow], ranks: Sequence[RankRow] = ()
) -> tuple[str, str, str]:
    """Three cost-table notes: each arm's rate, mean gain and cost per win;
    each arm's win@k; B and C against A (pairs, b, c, McNemar p, and the
    tasks left unpaired)."""
    tasks = len({(r.repo, r.rep) for r in rows})
    arms = [
        f"{label} {t.wins}/{t.held} won, gain {_gain(t.mean_gain)}, "
        f"{per(t.spend, t.wins)} USD/win"
        for label, t in _arms(rows).items()
    ]
    curves = []
    for label in _labels(rows):
        curve = win_curve(rows, ranks, label)
        wins = ",".join(str(curve[k][0]) for k in WIN_AT)
        curves.append(f"{label} {wins} of {curve[WIN_AT[0]][1]}")
    paired: list[str] = []
    for label in ("B", "C"):
        pairs, b, c, excluded = versus(rows, label)
        line = f"{label} vs A {len(pairs)} pair(s)"
        if pairs:
            line += f", b {b}, c {c}, p {mcnemar_exact(b, c):.4f}"
        paired.append(f"{line}, excl {excluded}")
    ks = "/".join(map(str, WIN_AT))
    return (
        f"OSS-AB arms after {tasks} task(s): " + "; ".join(arms),
        f"OSS-AB win in top {ks}: " + ("; ".join(curves) or "no task"),
        "OSS-AB paired: " + "; ".join(paired),
    )


@dataclass
class OssAbRecorder:
    """The module's rows; ``finish`` writes the summary once."""

    plan: OssAbPlan
    sink: ResultsSink
    distractors: frozenset[str]
    rows: list[AbRow] = field(default_factory=list)
    ranks: list[RankRow] = field(default_factory=list)

    def record(
        self,
        repo: OssRepo,
        rep: int,
        arm: OssArm,
        produced: ArmResult,
        outcome: CorpusOutcome | None,
        result: EngineRunResult | None = None,
        *,
        run: LiveRun,
        phase_cost: float,
        guard: str | None = None,
    ) -> None:
        """One row and its rank rows: ``outcome`` ``None`` and no ``guard``:
        no loop ran (no efficiency idea); a ``guard``: the task broke before
        the arm's loop (the generation guards, or the loop's clone)."""
        row = ab_row(
            repo.corpus, rep, arm.label, produced, outcome, self.distractors, result
        )
        if guard is not None:
            row = replace(row, status="not_run", guard=guard)
        ranked = rank_rows(
            row.repo, rep, arm.label, produced.hypotheses, result, guard=row.guard
        )
        self.rows.append(row)
        self.ranks.extend(ranked)
        self.sink.write(oss_record(row, arm, phase_cost, self.plan.n))
        for ranked_row in ranked:
            self.sink.write(ranked_row.record())
        run.note(run_note(row, kept_ranks(ranked)))

    def note_summary(self, run: LiveRun) -> None:
        for note in summary_notes(self.rows, self.ranks):
            run.note(note)

    def finish(self, echo: Callable[[str], None]) -> None:
        if self.rows:
            write_markdown(
                "OSS discovery A/B",
                render_oss_ab(self.rows, self.ranks),
                self.sink.environ,
                echo,
            )


# ---------------------------------------------------------------------------
# One task: what each live case runs
# ---------------------------------------------------------------------------


def _breach(exc: BaseException) -> str:
    return f"breach: {type(exc).__name__}: {exc}"


def run_task(
    repo: OssRepo,
    rep: int,
    *,
    live: StartLive,
    root: Path,
    isolation: Isolation,
    recorder: OssAbRecorder,
    policy: GitPolicy = PRODUCTION,
) -> None:
    """Phase 1, every arm's generation and every arm's loop for one (repo,
    rep); the running summary is noted on the task's last run, pass or fail."""
    plan = recorder.plan
    cfg = ab_settings(settings)
    playbook = load_playbook()
    with engine_settings(cfg):
        gen = live(gen_cap_usd(plan.arms, plan.n))
        last = gen
        try:
            try:
                phase = oss_phase_one(
                    repo, gen, root / "phase", isolation, policy=policy
                )
            except BaseException as exc:
                gen.note(f"OSS-AB {repo.name} rep {rep}: phase 1 {_breach(exc)}")
                raise
            budget = Budget(gen.cap_usd, gen.spent_usd)
            produced = {
                arm: generate(
                    arm, gen, budget, phase.facts, playbook=playbook, n=plan.n
                )
                for arm in plan.arms
            }
            record = functools.partial(
                recorder.record, repo, rep, phase_cost=phase.cost_usd
            )
            try:
                check_calls(gen, budget, list(produced.values()))
                check_untouched(phase)
            except BaseException as exc:
                for arm, found in produced.items():
                    record(arm, found, None, run=gen, guard=_breach(exc))
                raise
            for arm, found in produced.items():
                candidates = carry(found.hypotheses)
                if not candidates:
                    record(arm, found, None, run=gen)
                    continue
                last = run = live(plan.loop_cap(len(candidates)))
                try:
                    loop = start_arm_loop(
                        repo,
                        run,
                        root / arm.label,
                        isolation,
                        candidates,
                        policy=policy,
                    )
                except BaseException as exc:
                    record(arm, found, None, run=run, guard=_breach(exc))
                    raise
                run_engine(
                    loop,
                    run,
                    isolation,
                    model=cfg.ENGINE_MODEL,
                    record=functools.partial(record, arm, found, run=run),
                )
        finally:
            recorder.note_summary(last)
