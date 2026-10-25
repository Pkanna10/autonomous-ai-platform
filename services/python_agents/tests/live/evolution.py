"""Evolution (Window 0): does iterating compound gains on real code?

E5 deprioritised paper retrieval behind "playbook, lessons and evolution";
this experiment measures the evolution bet on real libraries of the OSS
corpus (``oss.OSS_CORPUS``, cloned at their pins).

**Repositories** (``$LIVE_EVOLVE_REPOS``, a comma list of corpus names):
by default the three with the largest delivered gains in the aimed OSS run
40061541473 (STATUS ledger): ``tabulate`` 14.3 %, ``tomli`` 13.3 % and
``markdown`` 10.2 % (``idna`` 10.1 % is next). Evolution asks whether a
second, third ... round finds more where one round already found
something; a library where one aimed round found nothing past the noise
would mostly measure that noise again. Three keep the default suite need
(103.5 USD) under live-smoke's 150 USD ceiling with room to spare.

**Rounds** (``$LIVE_EVOLVE_ROUNDS``, default and at most 10) per repository:

1. **Phase 1** on the clone as it stands: a zero-candidate engine run
   (``discovery.phase_one``'s recipe, every corpus guard) for the
   understanding, the profile and the objective of the code this round
   measures. It runs every round, not only the first: after a delivery the
   old profile names the cost the kept change removed.
2. **Blind generation**: one ``generate_hypotheses`` request on Sonnet 5.5
   at medium effort, no fallbacks (``discovery_ab.AB_ARM``), ``n`` = 5. From
   round 2 on, the generator is told what earlier rounds delivered (now in
   the code) and what they tried without surviving the judges.
   ``generate_hypotheses`` takes no lessons or history argument, so the
   history travels as engine-derived text appended to the objective's
   ``description`` (``with_history``): it reaches the request inside the
   untrusted fence like every other fact. Titles are model output, so they
   are reduced to plain one-line ASCII and capped; when the rounds outgrow
   ``HISTORY_MAX_CHARS`` the oldest are dropped first (``history_text``),
   so the latest failures always reach the generator.
3. **One whole engine loop** on the round's ``efficiency`` hypotheses
   (``discovery.carry``) on the clone, ``ENGINE_MODEL`` Sonnet 5.5, no
   fallbacks (``discovery_ab.ab_settings``), every corpus guard.
4. **The move**: when the loop delivered, the clone's ``main`` is
   fast-forwarded to the engine's delivered commit (``advance_clone``), so
   the next round's baseline is the improved code (re-baselining). A round
   that delivers nothing leaves the clone as it was.

**Stop rule**: a repository stops after ``EVOLVE_EMPTY_STOP`` (2)
consecutive empty rounds, or after the planned rounds. A round is empty
when it delivers nothing, including a round whose generation gave no
efficiency hypothesis (no engine loop runs then).

**Final winner's-curse check** (``retest_final``): after a repository's
last round, if any round delivered, the ORIGINAL base commit is measured
against the FINAL tip ABAB with the engine's own code: the combine
re-test's worktree phases (``phase_dirs``, ``owned_phases``,
``make_phase``), ``measure_abab`` (the same warm-ups and N =
``max(MIN_RUNS, runs)``) and the engine's frozen gain judge
(``MetricGainJudge`` with ``settings.NOISE_MULTIPLIER``: the gain must
clear the noise floor). It sends no Claude request, so it costs runner
time only, bounded by ``EVOLVE_RETEST_WALL_S``: every launch's timeout is
that bound over the number of launches (a timeout is a recorded
``RunFailure``, never a breach). The claimed cumulative gain (the
product of the per-round time ratios: 1 - prod(1 - g_k)) is recorded next
to the gain the re-test measures, with its floor and whether it holds.

``oss.start_oss_loop`` cannot serve a round: it always clones afresh and
wires the global settings, so ``start_round_loop`` is its tail on an
existing clone with ``corpus.start_loop``'s settings-copy wiring.

**The move keeps the repository guard.** Every run's guards
(``check_loop_guards``: the user's repository untouched except the engine's
own refs) are checked against a snapshot taken when that run starts, so
each round is checked against the clone as the round found it. The move
happens between rounds, after the round's guards held, and is itself
checked: only the engine's own ``engine/run-<id>`` branch at exactly the
delivered commit is accepted, which must descend from the base the round
measured (``state["base_commit"]``, the clone's ``HEAD``) and change no
protected path; git runs with the clone helper's hardening
(``oss._scratch_git``: no system or global config, no hooks, no prompt);
afterwards ``HEAD`` must be the commit on ``main`` and the snapshot must
differ only in ``refs/heads/main`` (status, config, hooks, info and every
other ref unchanged). Anything else is ``CloneRefusedError``, a recorded
breach. The final re-test must leave the clone's snapshot and worktree
list exactly as it found them (else a breach too).

**Caps**, sums of worst cases as in the other discovery suites: the
generation run (phase 1 plus the one generation request) is capped at
``EVOLVE_GEN_CAP_USD``; the engine run at ``$LIVE_EVOLVE_RUN_CAP_USD``
(default ``EVOLVE_RUN_CAP_USD``, 3 USD, at most ``oss.OSS_RUN_CAP_USD``).
The default plan needs 3 x 10 x (0.45 + 3.00) = 103.5 USD, so the run cap
did not have to come down for ten rounds; ``OSS_RUN_CAP_USD`` itself would
need 3 x 10 x 5.45 = 163.5 USD, past live-smoke's 150 USD ceiling. 3 USD is
ten times the OSS corpus's 0.30 USD a loop (on Opus, two candidates), and
each row says whether the cap shaped the round (``budget_flags``). The
generation bound ``EVOLVE_PROMPT_BOUND`` assumes OSS paths of at most
``OSS_PATH_BOUND`` characters and ASCII symbols (``test_evolution_guards``
measures the real request at those limits plus the largest history); a
larger fact can make the request refused before it is sent: the round is
then a recorded breach, never billed over the cap.

**Recorded, never asserted** (only the guards assert): per (repository,
round) whether it delivered, the titles it kept and tried, its gain and
noise floor against its own baseline, the cumulative gain against the
original code and its cost; per repository the final re-test; the
summary: the mean cumulative gain after rounds 1..R, how many repositories
improved in each later round, the cost per extra percentage point after
round 1 and how many final re-tests held. Notes reach the cost table (the
log), each within one cell: ``EVOLVE <repo> r<k>: ...`` per round,
``EVOLVE <repo> final: ...`` per repository, and the running summary.
"""

from __future__ import annotations

import functools
import math
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from typing import Final, Protocol

from e2e.conftest import Isolation, LaunchLog, UserRepo

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.transport import LLMTransport
from autonomous_ai_agents.common.config import IsolationMode, Settings, settings
from autonomous_ai_agents.common.models import (
    METRIC_WALL_TIME_S,
    Baseline,
    DeliveryKind,
    Hypothesis,
    JudgeOutcome,
    Measurement,
    Objective,
    Trial,
    TrialStatus,
    Workload,
)
from autonomous_ai_agents.execution.git import GitWorkspace
from autonomous_ai_agents.execution.measure import (
    AbabMeasured,
    Phase,
    make_phase,
    measure_abab,
)
from autonomous_ai_agents.execution.phase import owned_phases, phase_dirs
from autonomous_ai_agents.execution.procrun import RunFailure
from autonomous_ai_agents.optimization.anticheat import (
    check_path,
    compare_fingerprints,
)
from autonomous_ai_agents.optimization.generate import (
    GENERATE_MAX_TOKENS,
    MAX_TITLE_CHARS,
)
from autonomous_ai_agents.optimization.judges import MetricGainJudge, primary_metric
from autonomous_ai_agents.orchestrator.factory import build_context
from autonomous_ai_agents.orchestrator.main import EngineRunResult

from .conftest import SUITE_CAP_ENV, LiveRun, suite_cap
from .corpus import (
    CorpusOutcome,
    Loop,
    check_loop_guards,
    settings_editor,
    settings_trial_budget,
)
from .discovery import (
    PHASE_ONE_CAP_USD,
    PHASE_ONE_WORST_USD,
    ArmResult,
    RepoFacts,
    budget_flags,
    carry,
    ceil_usd,
    check_calls,
    check_untouched,
    generate_arm,
    read_phase_one,
    run_engine,
    worst_usd,
)
from .discovery_ab import AB_ARM, ab_settings
from .discovery_io import (
    ResultsSink,
    cells,
    env_number,
    env_whole,
    flag,
    json_line,
    write_markdown,
)
from .oss import (
    OSS_CORPUS,
    OSS_RUN_CAP_USD,
    PIN,
    PRODUCTION,
    CloneRefusedError,
    GitPolicy,
    OssRepo,
    _scratch_git,
    verify_head,
)

ROUNDS_ENV: Final = "LIVE_EVOLVE_ROUNDS"
REPOS_ENV: Final = "LIVE_EVOLVE_REPOS"
RUN_CAP_ENV: Final = "LIVE_EVOLVE_RUN_CAP_USD"
EVOLVE_ROUNDS: Final = 10
EVOLVE_MAX_ROUNDS: Final = 10
EVOLVE_EMPTY_STOP: Final = 2
"""Consecutive rounds without a delivery that end a repository's evolution."""
EVOLVE_DEFAULT_REPOS: Final = ("tabulate", "tomli", "markdown")
"""The largest delivered gains of the aimed OSS run 40061541473 (docstring)."""
EVOLVE_RUN_CAP_USD: Final = 3.0
EVOLVE_RETEST_WALL_S: Final = 900.0
"""The final re-test's wall-time bound: every launch's timeout is this over
the number of launches (git's own steps keep ``GIT_TIMEOUT_S``)."""
RETEST_TIP: Final = "evolve-tip"
RETEST_BASE: Final = "evolve-base"
RETEST_HYPOTHESIS: Final = "evolution"
EVOLVE_ARM: Final = AB_ARM
EVOLVE_N: Final = 5
EVOLVE_GENERATE_MAX_TOKENS: Final = GENERATE_MAX_TOKENS
"""The generator's default, as E3's n = 5 Sonnet arm ran (A/B's 8000 was for
n = 3): a truncated reply would lose the round."""
OSS_PATH_BOUND: Final = 100
"""The longest repository path the prompt bound assumes (the corpus's are
under 40 characters)."""
EVOLVE_PROMPT_BOUND: Final = 45_000
"""What ``call()`` may count for one round's generation request: 30
hotspots at the path bound and the profiler's symbol cap, every
understanding field at its cap, and the largest history (about 40,300
measured; the generation cap stays 0.45 USD up to a 50,000 bound)."""
HISTORY_TITLE_CHARS: Final = MAX_TITLE_CHARS
HISTORY_MAX_CHARS: Final = 6_000
HISTORY_LEAD: Final = (
    "Engine history, facts the engine measured on this project in earlier "
    "rounds (what they delivered is already in the code profiled here)"
)
EVOLVE_GEN_CAP_USD: Final = ceil_usd(
    PHASE_ONE_WORST_USD
    + worst_usd(EVOLVE_PROMPT_BOUND, EVOLVE_GENERATE_MAX_TOKENS, EVOLVE_ARM.model)
)
"""Phase 1's understand request and the round's generation, at their worst."""
NOTE_MAX_CHARS: Final = 200  # one cost-table cell (conftest._CELL_MAX)

# ---------------------------------------------------------------------------
# The plan and its caps
# ---------------------------------------------------------------------------


def _by_name(names: Sequence[str]) -> tuple[OssRepo, ...]:
    known = {repo.name: repo for repo in OSS_CORPUS}
    return tuple(known[name] for name in names)


EVOLVE_REPOS: Final = _by_name(EVOLVE_DEFAULT_REPOS)


def evolve_repos(environ: Mapping[str, str]) -> tuple[OssRepo, ...]:
    """``$LIVE_EVOLVE_REPOS``: unset is ``EVOLVE_REPOS``; else distinct
    corpus names separated by commas, in the order given."""
    if REPOS_ENV not in environ:
        return EVOLVE_REPOS
    raw = environ[REPOS_ENV]
    names = raw.split(",")
    known = {repo.name for repo in OSS_CORPUS}
    if any(n not in known for n in names) or len(set(names)) != len(names):
        raise ValueError(
            f"{REPOS_ENV} must list distinct OSS corpus names out of "
            f"{', '.join(sorted(known))}, got {raw!r}"
        )
    return _by_name(names)


@dataclass(frozen=True)
class EvolvePlan:
    rounds: int
    run_cap: float
    repos: tuple[OssRepo, ...] = EVOLVE_REPOS


def evolve_plan(environ: Mapping[str, str]) -> EvolvePlan:
    """Every knob, validated strictly (in the module fixture, before any spend)."""
    return EvolvePlan(
        rounds=env_whole(
            environ, ROUNDS_ENV, EVOLVE_ROUNDS, low=1, high=EVOLVE_MAX_ROUNDS
        ),
        run_cap=env_number(
            environ, RUN_CAP_ENV, EVOLVE_RUN_CAP_USD, high=OSS_RUN_CAP_USD
        ),
        repos=evolve_repos(environ),
    )


def evolve_need(plan: EvolvePlan) -> float:
    """The sum of the caps the suite may ask the ledger for: every round of
    every repository, each a generation run and an engine run (the final
    re-test sends no request)."""
    return len(plan.repos) * plan.rounds * (EVOLVE_GEN_CAP_USD + plan.run_cap)


def check_suite_cap(plan: EvolvePlan, environ: Mapping[str, str]) -> None:
    """Refuse a plan the suite cap cannot admit to the end, before any spend:
    the ledger would otherwise refuse a later round after earlier ones paid."""
    cap, need = suite_cap(environ), evolve_need(plan)
    if need > cap:
        raise ValueError(
            f"the evolution plan ({len(plan.repos)} repo(s) x {plan.rounds} "
            f"round(s), {plan.run_cap:g} USD an engine run) needs {need:.2f} USD "
            f"of caps; {SUITE_CAP_ENV} is {cap:.2f}"
        )


def evolve_settings(base: Settings) -> Settings:
    """The rounds' settings: Sonnet 5.5, no fallbacks (as the A/B's)."""
    return ab_settings(base)


# ---------------------------------------------------------------------------
# What the generator is told
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoundHistory:
    """One earlier round as the next generator sees it."""

    round: int
    delivered: tuple[str, ...]
    tried: tuple[str, ...]  # trialled, not delivered
    gain_pct: float | None
    generated: bool = True  # False: the round gave no efficiency hypothesis


def _plain(title: str) -> str:
    """A model-written title as one capped line of printable ASCII, with no
    character JSON would escape (quotes and backslashes are replaced)."""
    kept = "".join(c if c.isascii() and c.isprintable() else "?" for c in title)
    flat = " ".join(kept.split()).replace('"', "'").replace("\\", "/")
    return flat[:HISTORY_TITLE_CHARS]


def _titles(titles: Sequence[str]) -> str:
    return "; ".join(f'"{_plain(t)}"' for t in titles[:EVOLVE_N]) or "none"


def _history_part(past: RoundHistory) -> str:
    if not past.generated:
        return f"round {past.round}: generated no efficiency hypothesis."
    gain = "-" if past.gain_pct is None else f"{past.gain_pct:.1f}"
    done = (
        f"delivered with a {gain} % gain: {_titles(past.delivered)}"
        if past.delivered
        else "delivered nothing"
    )
    return (
        f"round {past.round}: {done}; tried without surviving the judges: "
        f"{_titles(past.tried)}."
    )


def history_text(history: Sequence[RoundHistory]) -> str:
    """The earlier rounds as one line of at most ``HISTORY_MAX_CHARS``
    (empty for round 1): the newest rounds first in, so the oldest are the
    ones left out (named) when they do not all fit."""
    if not history:
        return ""
    parts = [_history_part(past) for past in history]
    lead = f"{HISTORY_LEAD}: "
    for start in range(len(parts)):
        shown = parts[start:]
        omitted = (
            ""
            if start == 0
            else f"rounds {history[0].round}-{history[start - 1].round} not shown. "
        )
        text = lead + omitted + " ".join(shown)
        if len(text) <= HISTORY_MAX_CHARS:
            return text
    return (lead + parts[-1])[:HISTORY_MAX_CHARS]


def with_history(facts: RepoFacts, history: Sequence[RoundHistory]) -> RepoFacts:
    """``facts`` with the history appended to the objective's description
    (the only free-text fact the generator takes); round 1 unchanged."""
    if not history:
        return facts
    objective = facts.objective
    description = f"{objective.description}. {history_text(history)}"
    return replace(
        facts, objective=objective.model_copy(update={"description": description})
    )


def generate_round(run: LiveRun, budget: Budget, facts: RepoFacts) -> ArmResult:
    """The round's one generation request (Sonnet 5.5 medium, no fallbacks)."""
    return generate_arm(
        EVOLVE_ARM,
        run,
        budget,
        facts,
        n=EVOLVE_N,
        max_tokens=EVOLVE_GENERATE_MAX_TOKENS,
    )


# ---------------------------------------------------------------------------
# Gains
# ---------------------------------------------------------------------------


def compound(cumulative_pct: float, gain_pct: float | None) -> float:
    """The cumulative gain after one more round (``None``: no gain)."""
    gain = 0.0 if gain_pct is None else gain_pct
    return 100 * (1 - (1 - cumulative_pct / 100) * (1 - gain / 100))


def cumulative_pct(gains_pct: Sequence[float | None]) -> float:
    """1 - the product of (1 - g_k), in percent: each round's baseline is the
    previous round's delivered code, so the time ratios multiply."""
    total = 0.0
    for gain in gains_pct:
        total = compound(total, gain)
    return total


# ---------------------------------------------------------------------------
# The engine's delivery, and the clone moved to it
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Delivered:
    """A branch delivery: the run, its branch, the commit and the base the
    run measured."""

    run_id: str
    branch: str
    commit: str
    base: str | None


def delivered_of(result: EngineRunResult | None) -> Delivered | None:
    """The run's branch delivery with a commit, else ``None``."""
    if result is None:
        return None
    delivery = result.state["delivery"]
    if (
        delivery is None
        or delivery.kind is not DeliveryKind.branch
        or delivery.branch is None
        or delivery.commit is None
    ):
        return None
    state = result.state
    return Delivered(
        state["run_id"], delivery.branch, delivery.commit, state["base_commit"]
    )


def round_titles(
    result: EngineRunResult | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(delivered, tried): the titles in the delivered commit, and those
    trialled without reaching it, in the engine's order."""
    if result is None:
        return (), ()
    state = result.state
    names = {h.id: h.title for h in state["hypotheses"]}
    delivery = state["delivery"]
    verdicts = {v.id: v.hypothesis_id for v in state["verdicts"]}
    ids = () if delivery is None else delivery.verdict_ids
    delivered = [verdicts[v] for v in ids if v in verdicts]
    tried = [
        h
        for h in dict.fromkeys(t.hypothesis_id for t in state["trials"])
        if h not in delivered
    ]
    return (
        tuple(names.get(h, h) for h in delivered),
        tuple(names.get(h, h) for h in tried),
    )


def round_floor_pct(result: EngineRunResult | None) -> float | None:
    """The noise floor (percent) of the round's combination re-test on its
    primary metric, delivered or not; ``None`` when nothing was combined."""
    combination = None if result is None else result.state["combination"]
    if result is None or combination is None:
        return None
    metric = primary_metric(result.state["objectives"]) or METRIC_WALL_TIME_S
    floors = [
        j.noise_floor
        for j in combination.judge_results
        if j.metric == metric and j.noise_floor is not None
    ]
    return 100 * floors[0] if floors else None


def advance_clone(
    user: UserRepo,
    delivered: Delivered,
    *,
    policy: GitPolicy = PRODUCTION,
    environ: Mapping[str, str] | None = None,
) -> UserRepo:
    """``main`` fast-forwarded to the engine's delivered commit (module
    docstring); the clone at it, or ``CloneRefusedError`` before git moves."""
    branch = f"{settings.TRIAL_BRANCH_PREFIX}run-{delivered.run_id}"
    if delivered.branch != branch:
        raise CloneRefusedError(
            f"{delivered.branch!r} is not the engine's delivery branch {branch!r}"
        )
    if PIN.fullmatch(delivered.commit) is None:
        raise CloneRefusedError(f"{delivered.commit!r} is not a full commit id")
    if delivered.base != user.base:
        raise CloneRefusedError(
            f"the run measured {delivered.base}, not the clone's base {user.base}"
        )
    before = user.snapshot()
    if (before.head, before.head_ref) != (user.base, "refs/heads/main"):
        raise CloneRefusedError(
            f"HEAD is {before.head} on {before.head_ref}, not {user.base} on main"
        )
    ref = f"refs/heads/{branch}"
    if before.refs.get(ref) != delivered.commit:
        raise CloneRefusedError(f"{ref} is not at {delivered.commit}")
    with _scratch_git(user.path, policy, environ) as git:
        try:
            git("merge-base", "--is-ancestor", user.base, delivered.commit)
        except CloneRefusedError:
            raise CloneRefusedError(
                f"{delivered.commit} is not a descendant of {user.base}"
            ) from None
        changed = git(
            "diff", "--no-ext-diff", "--no-textconv", "--no-renames",
            "--name-only", "-z", user.base, delivered.commit, "--",
        )  # fmt: skip
        for path in filter(None, changed.split("\0")):
            if check_path(path) is not None:
                raise CloneRefusedError(f"the delivery changes protected {path!r}")
        git("checkout", "-q", "-B", "main", delivered.commit)
    verify_head(user.path, delivered.commit, policy=policy, environ=environ)
    after = user.snapshot()
    unchanged = (before.status, before.config, before.hooks, before.info)
    if (
        after.refs != {**before.refs, "refs/heads/main": delivered.commit}
        or (
            after.status,
            after.config,
            after.hooks,
            after.info,
        )
        != unchanged
    ):
        raise CloneRefusedError("moving the clone changed more than main")
    return UserRepo(user.path, delivered.commit)


# ---------------------------------------------------------------------------
# The final winner's-curse check: original base vs final tip, ABAB
# ---------------------------------------------------------------------------

AbabMeasure = Callable[[Phase, Phase, Workload], AbabMeasured]
"""``measure.measure_abab`` (a fake measurer in the guards)."""


@dataclass(frozen=True)
class FinalRetest:
    """The original base against the final tip (recorded, never asserted)."""

    gain_pct: float | None  # None: not measured (a RunFailure) or no rows
    floor_pct: float | None
    holds: bool  # the frozen gain judge passed: the gain clears the floor
    same_output: bool | None  # every workload's output fingerprint agreed
    reason: str
    wall_s: float
    bound_s: float
    launch_timeout_s: float
    launches: int = 0  # recorded launches, every one sandboxed and isolated


def launch_timeout_s(workloads: Sequence[Workload], bound_s: float) -> float:
    """``bound_s`` over every launch the ABAB re-test makes (each side's
    warm-ups and ``max(MIN_RUNS, runs)`` timed runs, per workload)."""
    launches = sum(
        2 * (w.warmup_runs + max(settings.MIN_RUNS, w.runs)) for w in workloads
    )
    return bound_s / launches


def retest_final(
    user: UserRepo,
    base: str,
    workloads: Sequence[Workload],
    objectives: Sequence[Objective],
    *,
    mode: IsolationMode,
    noise_multiplier: float,
    run_id: str,
    bound_s: float = EVOLVE_RETEST_WALL_S,
    measure: AbabMeasure = measure_abab,
    clock: Callable[[], float] = time.monotonic,
) -> FinalRetest:
    """``base`` (the original pin) against the clone's ``HEAD`` (the final
    tip) as the combine re-test measures and judges (module docstring).
    A ``RunFailure`` is a recorded result; a clone left changed, a tip
    that does not descend from ``base``, or a launch the ``LaunchLog``
    recorded as not ``required`` or not isolated (``check_sandboxed``'s
    rule, even when the measurement then failed), is ``CloneRefusedError``."""
    tip = user.base
    for what, commit in (("base", base), ("tip", tip)):
        if PIN.fullmatch(commit) is None:
            raise CloneRefusedError(f"the {what} {commit!r} is not a full commit id")
    if base == tip or not workloads:
        raise ValueError("the final re-test needs a moved tip and a workload")
    per_launch = launch_timeout_s(workloads, bound_s)
    bounded = tuple(
        w.model_copy(update={"timeout_s": min(w.timeout_s, per_launch)})
        for w in workloads
    )
    before, trees = user.snapshot(), user.worktrees()
    git = GitWorkspace(user.path)
    if not git.is_ancestor(base, tip):
        raise CloneRefusedError(f"the tip {tip} does not descend from {base}")
    tip_dirs, base_dirs = (
        phase_dirs(run_id, RETEST_TIP),
        phase_dirs(run_id, RETEST_BASE),
    )
    rows_a: list[Measurement] = []
    rows_b: list[Measurement] = []
    failure: str | None = None
    launches = LaunchLog()
    started = clock()
    with owned_phases(git, "the evolution re-test", tip_dirs, base_dirs):
        tip_wt = git.add_worktree(tip_dirs.worktree, tip)
        base_wt = git.add_worktree(base_dirs.worktree, base)
        b = make_phase(
            git, tip_wt, scratch=tip_dirs.scratch, probe=tip_dirs.probe,
            network=mode, fs=mode, run=launches,
        )  # fmt: skip
        a = make_phase(
            git, base_wt, scratch=base_dirs.scratch, probe=base_dirs.probe,
            network=mode, fs=mode, run=launches,
        )  # fmt: skip
        try:
            for workload in bounded:
                abab = measure(a, b, workload)
                rows_a.extend(abab.a)
                rows_b.extend(abab.b)
        except RunFailure as exc:
            failure = exc.reason
    wall = clock() - started
    if user.snapshot() != before or user.worktrees() != trees:
        raise CloneRefusedError("the final re-test changed the clone")
    for launch in launches.launches:
        sandboxed = (launch.network, launch.fs) == ("required", "required")
        if not (sandboxed and launch.net_isolated and launch.fs_isolated):
            raise CloneRefusedError(f"a re-test launch was not sandboxed: {launch}")
    common = {"wall_s": wall, "bound_s": bound_s, "launch_timeout_s": per_launch}
    count = len(launches.launches)
    if failure is not None:
        reason = f"not re-tested: {failure}"[:300]
        return FinalRetest(None, None, False, None, reason, **common, launches=count)
    judged = _judged(base, tip, rows_a, rows_b, objectives, noise_multiplier, common)
    return replace(judged, launches=count)


def _judged(
    base: str,
    tip: str,
    rows_a: Sequence[Measurement],
    rows_b: Sequence[Measurement],
    objectives: Sequence[Objective],
    noise_multiplier: float,
    common: Mapping[str, float],
) -> FinalRetest:
    """The engine's gain judge on the interleaved rows (A: the base)."""
    metric = primary_metric(objectives) or METRIC_WALL_TIME_S
    judge = MetricGainJudge(metric=metric, noise_multiplier=noise_multiplier)
    result = judge.evaluate(
        Baseline(commit=base, measurements=tuple(rows_a), objectives=tuple(objectives)),
        Trial(
            hypothesis_id=RETEST_HYPOTHESIS,
            round=1,
            base_commit=base,
            commit=tip,
            status=TrialStatus.measured,
            measurements=tuple(rows_b),
        ),
    )
    return FinalRetest(
        gain_pct=None if result.gain is None else 100 * result.gain,
        floor_pct=None if result.noise_floor is None else 100 * result.noise_floor,
        holds=result.outcome is JudgeOutcome.passed,
        same_output=(not compare_fingerprints(rows_a, rows_b)) if rows_a else None,
        reason=result.reason[:300],
        wall_s=common["wall_s"],
        bound_s=common["bound_s"],
        launch_timeout_s=common["launch_timeout_s"],
    )


# ---------------------------------------------------------------------------
# One round's loops
# ---------------------------------------------------------------------------


def _no_factory(cfg: Settings) -> LLMTransport:
    raise AssertionError("the evolution must use the captured transport")


def start_round_loop(
    repo: OssRepo,
    run: LiveRun,
    user: UserRepo,
    isolation: Isolation,
    cfg: Settings,
    candidates: Sequence[Hypothesis],
    *,
    cap_usd: float | None = None,
) -> Loop:
    """``start_oss_loop``'s wiring on the existing clone ``user``, with
    ``corpus.start_loop``'s ``cfg`` copy (chain, editor, trial budget);
    ``candidates`` rebound to the project, capped at ``cap_usd`` (at most
    the run's cap)."""
    before = user.snapshot()
    project = repo.project(user.path)
    chosen = tuple(h.model_copy(update={"project_id": project.id}) for h in candidates)
    launches = LaunchLog()
    transport = run.transport(cfg)
    context = build_context(
        project,
        candidates=chosen,
        transport=transport,
        transport_factory=_no_factory,
        editor=settings_editor(transport, cfg),
        min_trial_budget_usd=settings_trial_budget(cfg),
        network=isolation.mode,
        fs=isolation.mode,
        run=launches,
    )
    cap = run.cap_usd if cap_usd is None else min(cap_usd, run.cap_usd)
    return Loop(
        repo.corpus,
        user,
        before,
        project,
        repo.workload(project),
        chosen,
        launches,
        context,
        cap,
        "blind",
    )


@dataclass(frozen=True)
class Generated:
    """Phase 1's spend and the round's generation."""

    phase_cost_usd: float
    produced: ArmResult


@dataclass(frozen=True)
class Improved:
    """The round's engine loop: its outcome and its final state."""

    outcome: CorpusOutcome
    result: EngineRunResult | None


class RoundSteps(Protocol):
    def generate(
        self,
        run: LiveRun,
        round_no: int,
        user: UserRepo,
        history: Sequence[RoundHistory],
    ) -> Generated: ...

    def improve(
        self, run: LiveRun, user: UserRepo, candidates: Sequence[Hypothesis]
    ) -> Improved: ...

    def advance(self, user: UserRepo, delivered: Delivered) -> UserRepo: ...

    def retest(
        self, user: UserRepo, base: str, last: EngineRunResult
    ) -> FinalRetest: ...


@dataclass(frozen=True)
class LiveSteps:
    """The real rounds on one OSS clone (``RoundSteps``)."""

    repo: OssRepo
    isolation: Isolation
    cfg: Settings
    policy: GitPolicy = PRODUCTION
    measure: AbabMeasure = measure_abab

    def generate(
        self,
        run: LiveRun,
        round_no: int,
        user: UserRepo,
        history: Sequence[RoundHistory],
    ) -> Generated:
        if run.records:
            raise ValueError("phase one must be the first spend of its run")
        loop = start_round_loop(
            self.repo,
            run,
            user,
            self.isolation,
            self.cfg,
            (),
            cap_usd=PHASE_ONE_CAP_USD,
        )
        result = loop.run()
        check_loop_guards(loop, run, result, self.isolation)
        phase = read_phase_one(loop, run, result)
        budget = Budget(run.cap_usd, run.spent_usd)
        produced = generate_round(run, budget, with_history(phase.facts, history))
        check_calls(run, budget, [produced])
        check_untouched(phase)
        return Generated(phase.cost_usd, produced)

    def improve(
        self, run: LiveRun, user: UserRepo, candidates: Sequence[Hypothesis]
    ) -> Improved:
        loop = start_round_loop(
            self.repo, run, user, self.isolation, self.cfg, candidates
        )
        seen: list[EngineRunResult | None] = []

        def record(_outcome: CorpusOutcome, result: EngineRunResult | None) -> None:
            seen.append(result)

        outcome = run_engine(
            loop, run, self.isolation, model=self.cfg.ENGINE_MODEL, record=record
        )
        return Improved(outcome, seen[-1])

    def advance(self, user: UserRepo, delivered: Delivered) -> UserRepo:
        return advance_clone(user, delivered, policy=self.policy)

    def retest(self, user: UserRepo, base: str, last: EngineRunResult) -> FinalRetest:
        """The final re-test with the last engine run's resolved workloads
        and objectives (what its own combine re-test measured)."""
        state = last.state
        return retest_final(
            user,
            base,
            state["workloads"],
            state["objectives"],
            mode=self.isolation.mode,
            noise_multiplier=self.cfg.NOISE_MULTIPLIER,
            run_id=f"evolve-{uuid.uuid4().hex[:12]}",
            measure=self.measure,
        )


# ---------------------------------------------------------------------------
# Rows, notes and the summary
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvolveRow:
    """One (repository, round) (recorded, never asserted)."""

    repo: str
    round: int
    status: str  # the engine status, "no_hypotheses", or "error" (a breach)
    delivered: bool
    commit: str | None
    kept: tuple[str, ...]  # in the delivered commit (now in the code)
    verdict_kept: tuple[str, ...]  # keep verdicts, combined or not
    tried: tuple[str, ...]  # trialled without reaching the delivered commit
    gain_pct: float | None  # against the round's own baseline
    floor_pct: float | None  # the round's combination re-test noise floor
    cumulative_pct: float  # against the original code
    phase_cost_usd: float
    generation_cost_usd: float
    engine_cost_usd: float
    candidates: int  # handed to the loop (efficiency class only)
    dropped: int  # generated, but behaviour or novel
    history_rounds: int  # earlier rounds the generator was told about
    engine_model: str
    served_models: tuple[str, ...]
    guard: str
    generation_error: str | None
    budget_exhausted: bool | None  # None: no loop ran
    trial_budget_error: bool

    @property
    def cost_usd(self) -> float:
        return self.phase_cost_usd + self.generation_cost_usd + self.engine_cost_usd

    @property
    def trialled(self) -> int:
        """Hypotheses the round trialled (delivered or not)."""
        return len(self.kept) + len(self.tried)

    def record(self) -> dict[str, object]:
        return {"experiment": "evolve", **asdict(self), "cost_usd": self.cost_usd}


@dataclass(frozen=True)
class EvolveFinal:
    """One repository's end: the claimed gain and the final re-test."""

    repo: str
    rounds: int
    delivered_rounds: int
    base: str
    tip: str
    claimed_pct: float  # 1 - prod(1 - g_k) over the delivered rounds
    retest: FinalRetest | None  # None: nothing delivered, nothing re-tested
    guard: str = "ok"

    def record(self) -> dict[str, object]:
        return {"experiment": "evolve-final", **asdict(self)}


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}%"


def round_note(row: EvolveRow) -> str:
    """``EVOLVE <repo> r<k>: delivered <yes/no> gain <g> floor <f> tried
    <n>``, then the status and the guard when either is not the norm."""
    note = (
        f"EVOLVE {row.repo} r{row.round}: delivered {flag(row.delivered)} gain "
        f"{_pct(row.gain_pct)} floor {_pct(row.floor_pct)} tried {row.trialled}"
    )
    if row.status != "done":
        note += f", status {row.status}"
    if row.guard != "ok":
        note += f", {row.guard}"
    return note[:NOTE_MAX_CHARS]


def final_note(final: EvolveFinal) -> str:
    """``EVOLVE <repo> final: rounds <r> claimed <c> retest <m> floor <f>
    holds <yes/no>`` (``-``: nothing was delivered, so nothing re-tested)."""
    retest = final.retest
    note = (
        f"EVOLVE {final.repo} final: rounds {final.rounds} claimed "
        f"{_pct(final.claimed_pct)} retest "
        f"{_pct(None if retest is None else retest.gain_pct)} floor "
        f"{_pct(None if retest is None else retest.floor_pct)} holds "
        f"{flag(None if retest is None else retest.holds)}"
    )
    if retest is not None and retest.gain_pct is None:
        note += f", {retest.reason}"
    if final.guard != "ok":
        note += f", {final.guard}"
    return note[:NOTE_MAX_CHARS]


@dataclass(frozen=True)
class EvolveSummary:
    repos: int  # every row held the guards
    excluded: int  # a repository with a breach
    mean_cumulative: tuple[float, ...]  # after rounds 1..R
    improved: dict[int, tuple[int, int]]  # round -> (delivered, reached it)
    first_cost: float
    first_pp: float
    extra_cost: float  # rounds 2+
    extra_pp: float  # cumulative after R minus after round 1, summed
    retested: int  # final re-tests that measured
    held: int  # of those, the ones that cleared the floor


def _after(rows: Sequence[EvolveRow], k: int) -> float:
    done = [r for r in rows if r.round <= k]
    return done[-1].cumulative_pct if done else 0.0


def summarise(
    rows: Sequence[EvolveRow],
    *,
    rounds: int,
    finals: Sequence[EvolveFinal] = (),
) -> EvolveSummary:
    by_repo: dict[str, list[EvolveRow]] = {}
    for row in rows:
        by_repo.setdefault(row.repo, []).append(row)
    breached = {f.repo for f in finals if f.guard != "ok"}
    kept = {
        name: sorted(group, key=lambda r: r.round)
        for name, group in by_repo.items()
        if all(r.guard == "ok" for r in group) and name not in breached
    }
    groups = list(kept.values())
    means = tuple(
        math.fsum(_after(g, k) for g in groups) / len(groups) if groups else 0.0
        for k in range(1, rounds + 1)
    )
    flat = [r for g in groups for r in g]
    improved = {
        k: (
            sum(r.delivered for r in flat if r.round == k),
            sum(r.round == k for r in flat),
        )
        for k in range(2, rounds + 1)
    }
    measured = [
        f.retest
        for f in finals
        if f.repo in kept and f.retest is not None and f.retest.gain_pct is not None
    ]
    return EvolveSummary(
        repos=len(groups),
        excluded=len(set(by_repo) | breached) - len(groups),
        mean_cumulative=means,
        improved=improved,
        first_cost=math.fsum(r.cost_usd for r in flat if r.round == 1),
        first_pp=math.fsum(_after(g, 1) for g in groups),
        extra_cost=math.fsum(r.cost_usd for r in flat if r.round > 1),
        extra_pp=math.fsum(_after(g, rounds) - _after(g, 1) for g in groups),
        retested=len(measured),
        held=sum(r.holds for r in measured),
    )


def _per_pp(cost: float, pp: float) -> str:
    return f"{cost / pp:.4f}" if pp > 0 else "n/a"


def summary_notes(summary: EvolveSummary) -> tuple[str, str]:
    """The running summary in two cost-table cells (the decision's figures):
    the mean cumulative gain by round, then the later rounds' hits, the
    cost per extra point and the final re-tests."""
    means = "/".join(f"{m:.1f}" for m in summary.mean_cumulative)
    better = " ".join(f"{hit}/{ran}" for hit, ran in summary.improved.values())
    first = (
        f"EVOLVE summary over {summary.repos} repo(s) ({summary.excluded} "
        f"excluded): mean cumulative % by round {means}"
    )
    second = (
        f"EVOLVE summary: improved by round 2.. {better or 'n/a'}; USD per extra "
        f"pp after round 1 {_per_pp(summary.extra_cost, summary.extra_pp)} (round "
        f"1 {_per_pp(summary.first_cost, summary.first_pp)}); final re-test held "
        f"{summary.held}/{summary.retested}"
    )
    return first[:NOTE_MAX_CHARS], second[:NOTE_MAX_CHARS]


def _num(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def _final_lines(finals: Sequence[EvolveFinal]) -> list[str]:
    lines = [
        "",
        "| repo | rounds | delivered rounds | claimed % | re-test % | floor % "
        "| holds | same output | wall s | guards |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: | --- |",
    ]
    for f in finals:
        r = f.retest
        lines.append(
            cells(
                [
                    f.repo,
                    f.rounds,
                    f.delivered_rounds,
                    _num(f.claimed_pct),
                    _num(None if r is None else r.gain_pct),
                    _num(None if r is None else r.floor_pct),
                    flag(None if r is None else r.holds),
                    flag(None if r is None else r.same_output),
                    "-" if r is None else f"{r.wall_s:.0f}",
                    f.guard,
                ]
            )
        )
    return lines


def render_evolve(
    rows: Sequence[EvolveRow],
    *,
    rounds: int,
    finals: Sequence[EvolveFinal] = (),
) -> str:
    lines = ["## Evolution on real code", ""]
    if not rows:
        return "\n".join([*lines, "No evolution round finished."])
    lines += [
        "| repo | round | status | delivered | gain % | floor % | cumulative % "
        "| kept | tried | USD | cap hit | guards |",
        "| --- | ---: | --- | --- | ---: | ---: | ---: | --- | --- | ---: | --- "
        "| --- |",
    ]
    for r in rows:
        hit = r.budget_exhausted is True or r.trial_budget_error
        lines.append(
            cells(
                [
                    r.repo,
                    r.round,
                    r.status,
                    flag(r.delivered),
                    _num(r.gain_pct),
                    _num(r.floor_pct),
                    f"{r.cumulative_pct:.1f}",
                    "; ".join(r.kept) or "-",
                    "; ".join(r.tried) or "-",
                    f"{r.cost_usd:.4f}",
                    "-" if r.budget_exhausted is None else flag(hit),
                    r.guard if r.generation_error is None else r.generation_error,
                ]
            )
        )
    if finals:
        lines += _final_lines(finals)
    s = summarise(rows, rounds=rounds, finals=finals)
    lines.append("")
    for k, mean in enumerate(s.mean_cumulative, 1):
        lines.append(
            f"After round {k}: mean cumulative gain {mean:.1f} % over {s.repos} repo(s)."
        )
    for k, (hits, ran) in s.improved.items():
        lines.append(
            f"Improved in round {k}: {hits} of the {ran} repo(s) that reached it."
        )
    lines += [
        f"Rounds 2+: {s.extra_cost:.4f} USD for {s.extra_pp:.2f} pp "
        f"({_per_pp(s.extra_cost, s.extra_pp)} USD per pp); round 1: "
        f"{s.first_cost:.4f} USD for {s.first_pp:.2f} pp "
        f"({_per_pp(s.first_cost, s.first_pp)} USD per pp).",
        f"Final re-test (original base vs final tip, ABAB): {s.held} of "
        f"{s.retested} held past the noise floor.",
        f"Excluded: {s.excluded} repo(s) with a guard breach.",
        "Each round: phase 1 on the clone as it stands, one Sonnet 5.5 medium "
        f"generation (n = {EVOLVE_N}, told what earlier rounds delivered and "
        "tried), one engine loop (Sonnet 5.5, no fallbacks); a delivered round "
        f"moves the clone to its commit; {EVOLVE_EMPTY_STOP} empty rounds in a "
        "row end the repository.",
    ]
    return "\n".join(lines)


@dataclass
class EvolveRecorder:
    """The module's rows; ``finish`` writes the summary and every row once."""

    plan: EvolvePlan
    sink: ResultsSink
    rows: list[EvolveRow] = field(default_factory=list)
    finals: list[EvolveFinal] = field(default_factory=list)

    def record(self, row: EvolveRow, run: LiveRun) -> None:
        self.rows.append(row)
        self.sink.write(row.record())
        run.note(round_note(row))

    def record_final(self, final: EvolveFinal, run: LiveRun) -> None:
        self.finals.append(final)
        self.sink.write(final.record())
        run.note(final_note(final))

    def summary(self, run: LiveRun) -> None:
        summary = summarise(self.rows, rounds=self.plan.rounds, finals=self.finals)
        for note in summary_notes(summary):
            run.note(note)

    def finish(self, echo: Callable[[str], None]) -> None:
        """The markdown summary, then each row in full (a table cell is
        capped and the results artifact may be out of the reader's reach)."""
        if not self.rows:
            return
        text = render_evolve(self.rows, rounds=self.plan.rounds, finals=self.finals)
        write_markdown("Evolution", text, self.sink.environ, echo)
        for row in self.rows:
            echo("row " + json_line(row.record()))
        for final in self.finals:
            echo("final " + json_line(final.record()))


# ---------------------------------------------------------------------------
# The driver
# ---------------------------------------------------------------------------


def _row(
    name: str,
    round_no: int,
    previous: float,
    history_rounds: int,
    gen: LiveRun,
    generated: Generated | None,
    run: LiveRun | None,
    improved: Improved | None,
    *,
    error: BaseException | None = None,
) -> EvolveRow:
    """The round's row from whatever it reached; ``error``: a breach."""
    produced = None if generated is None else generated.produced
    candidates = () if produced is None else carry(produced.hypotheses)
    outcome = None if improved is None else improved.outcome
    result = None if improved is None else improved.result
    kept, tried = round_titles(result)
    delivered = outcome is not None and outcome.delivered
    gain = outcome.gain_pct if outcome is not None and delivered else None
    found = delivered_of(result) if delivered else None
    flags = budget_flags(result)
    if error is not None:
        status, guard = "error", f"breach: {type(error).__name__}: {error}"
    elif outcome is None:
        status, guard = "no_hypotheses", "ok"
    else:
        status, guard = outcome.status, outcome.guard
    return EvolveRow(
        repo=name,
        round=round_no,
        status=status,
        delivered=delivered,
        commit=None if found is None else found.commit,
        kept=kept,
        verdict_kept=() if outcome is None else outcome.kept,
        tried=tried,
        gain_pct=gain,
        floor_pct=round_floor_pct(result),
        cumulative_pct=compound(previous, gain),
        phase_cost_usd=gen.spent_usd if generated is None else generated.phase_cost_usd,
        generation_cost_usd=0.0 if produced is None else produced.cost_usd,
        engine_cost_usd=0.0 if run is None else run.spent_usd,
        candidates=len(candidates),
        dropped=0 if produced is None else len(produced.hypotheses) - len(candidates),
        history_rounds=history_rounds,
        engine_model=EVOLVE_ARM.model if outcome is None else outcome.engine_model,
        served_models=() if outcome is None else outcome.served_models,
        guard=guard,
        generation_error=None if produced is None else produced.error,
        budget_exhausted=flags.budget_exhausted,
        trial_budget_error=flags.trial_budget_error,
    )


def should_stop(delivered: Sequence[bool]) -> bool:
    """The stop rule: the last ``EVOLVE_EMPTY_STOP`` rounds delivered nothing."""
    tail = delivered[-EVOLVE_EMPTY_STOP:]
    return len(tail) == EVOLVE_EMPTY_STOP and not any(tail)


@dataclass
class _Repo:
    """One repository's evolution as it goes."""

    name: str
    base: str
    user: UserRepo
    history: list[RoundHistory] = field(default_factory=list)
    rows: list[EvolveRow] = field(default_factory=list)
    last: EngineRunResult | None = None  # the latest engine run with a state


def _round(
    repo: _Repo,
    round_no: int,
    steps: RoundSteps,
    start_gen: Callable[[], LiveRun],
    start_engine: Callable[[], LiveRun],
    recorder: EvolveRecorder,
) -> EvolveRow:
    """One round, recorded as it ends (a breach too, then raised again)."""
    told = tuple(repo.history)
    cumulative = repo.rows[-1].cumulative_pct if repo.rows else 0.0
    gen = start_gen()
    row_of = functools.partial(_row, repo.name, round_no, cumulative, len(told), gen)
    try:
        generated = steps.generate(gen, round_no, repo.user, told)
    except BaseException as exc:
        recorder.record(row_of(None, None, None, error=exc), gen)
        raise
    candidates = carry(generated.produced.hypotheses)
    if not candidates:
        row = row_of(generated, None, None)
        recorder.record(row, gen)
        repo.history.append(RoundHistory(round_no, (), (), None, generated=False))
        return row
    run = start_engine()
    improved: Improved | None = None
    try:
        improved = steps.improve(run, repo.user, candidates)
        row = row_of(generated, run, improved)
        if improved.result is not None:
            repo.last = improved.result
        if row.delivered:
            found = delivered_of(improved.result)
            if found is None:
                raise AssertionError("a branch delivery without a commit")
            repo.user = steps.advance(repo.user, found)
    except BaseException as exc:
        recorder.record(row_of(generated, run, improved, error=exc), run)
        raise
    recorder.record(row, run)
    repo.history.append(RoundHistory(round_no, row.kept, row.tried, row.gain_pct))
    return row


def _final(
    repo: _Repo, steps: RoundSteps, recorder: EvolveRecorder, run: LiveRun
) -> EvolveFinal:
    """The winner's-curse check after the last round (nothing delivered:
    nothing to re-test); a breach is recorded, then raised again."""
    delivered = [r for r in repo.rows if r.delivered]
    final = EvolveFinal(
        repo=repo.name,
        rounds=len(repo.rows),
        delivered_rounds=len(delivered),
        base=repo.base,
        tip=repo.user.base,
        claimed_pct=cumulative_pct([r.gain_pct for r in delivered]),
        retest=None,
    )
    if delivered:
        if repo.last is None:
            raise AssertionError("a delivered round without an engine state")
        try:
            final = replace(final, retest=steps.retest(repo.user, repo.base, repo.last))
        except BaseException as exc:
            recorder.record_final(
                replace(final, guard=f"breach: {type(exc).__name__}: {exc}"), run
            )
            raise
    recorder.record_final(final, run)
    return final


def run_evolution(
    name: str,
    user: UserRepo,
    plan: EvolvePlan,
    steps: RoundSteps,
    *,
    start_gen: Callable[[], LiveRun],
    start_engine: Callable[[], LiveRun],
    recorder: EvolveRecorder,
) -> tuple[EvolveRow, ...]:
    """Up to ``plan.rounds`` rounds on ``user`` until the stop rule
    (``should_stop``), then the final re-test; every round and the final
    are recorded as they end, a breach too (then raised again); the running
    summary is noted on the repository's last run either way."""
    repo = _Repo(name, user.base, user)
    runs: list[LiveRun] = []

    def tracked(start: Callable[[], LiveRun]) -> Callable[[], LiveRun]:
        def make() -> LiveRun:
            runs.append(start())
            return runs[-1]

        return make

    try:
        for round_no in range(1, plan.rounds + 1):
            row = _round(
                repo,
                round_no,
                steps,
                tracked(start_gen),
                tracked(start_engine),
                recorder,
            )
            repo.rows.append(row)
            if should_stop([r.delivered for r in repo.rows]):
                break
        _final(repo, steps, recorder, runs[-1])
    finally:
        if runs:
            recorder.summary(runs[-1])
    return tuple(repo.rows)
