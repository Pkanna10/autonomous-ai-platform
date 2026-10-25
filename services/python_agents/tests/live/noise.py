"""Runner noise calibration (Window 0): how noisy are timings on a GitHub runner?

The judges prove a gain only past ``max(2 stdev, MIN_RELATIVE_GAIN)`` of the
baseline (``anticheat.exceeds_noise``). On the ``lettertally`` control the
A/B run 40063812021 still saw 2.8 % and 3.8 % "gains" clear that floor, and
4/10 aimed OSS gains fell below it. This suite measures the noise itself,
with nothing changed (an A/A test), so the floor and Step 3's paired noise
rule are set from data:

- Targets (``NOISE_TARGETS``): every ``oss.OSS_CORPUS`` library cloned at its
  pin (``oss.prepare_repo``), then every ``corpus.CORPUS`` control
  (``make_repo``). Each workload is the one the corpus suites hand the
  engine (``workload_argv``): the caller supplies it, never understand, so
  no Claude request is needed (cap 0 USD).
- Per target: the engine's own connect and baseline path, K times on the
  unchanged base: ``GitPreflight.check`` (in the sandbox; it resolves
  ``python`` as connect does), then ``GitBaselineRunner.measure`` with a
  fresh run id each time (its own worktree, one warm-up, N timed runs,
  every launch through ``run_once`` in the ``required`` sandbox), and the
  baseline node's trust checks (``measurement_violations``,
  ``_require_trustworthy_baseline``) and noisy-host check (``_noise``). The
  project has no test command: the suite is one launch after the timed
  runs, it times nothing, and leaving it out buys K.
- Statistics (``summarize_repo``): the within-baseline CV (median of the K
  samples' stdev over mean, what the noisy-host check sees) of wall time
  and peak RSS, the between-baseline CV of the K means, the engine's floor,
  the noisy baselines; the A/A test (``aa_counts``): for every ordered pair
  (i, j) the real ``SpeedJudge`` judges baseline j as a trial against i
  (a pass is a false win), the whole verdict over the active default
  judges (a ``keep`` would ship), and the real ``MemoryJudge`` under a
  peak-memory objective; the 95th percentile of |relative difference| of
  the means over those pairs (the floor a paired rule would need).
- Records, never asserted: one JSON line per target and one summary to
  ``$LIVE_RESULTS_PATH``, a table to the job summary and the log, and the
  notes ``NOISE <repo>: ...``, ``NOISE spread <repo>: ...``,
  ``NOISE summary: ...`` and ``NOISE summary detail: ...`` in the cost table.
- Guards (``check_noise_guards``): no request on the wire (the cap is the
  sum of no worst case), every launch ``required`` and isolated, only the
  preflight and baseline phases ran, the user's repository untouched.
- Wall time (``estimate_s``): per target its setup plus K baselines of
  ``baseline_runs()`` launches at the profile's plain seconds (OSS
  manifest, measured on the Lead's container) times ``RUNNER_SLOWDOWN``
  plus a launch overhead. The default K=6 is about 24 minutes, K=10 about
  37; past ``WALL_BUDGET_S`` (60 minutes) K scales down, and a plan where
  even K=2 does not fit is refused before any run. The slowdown and setup
  constants are guesses, so the budget is also enforced at run time: a
  target that would start past it is skipped and recorded (``skipped``
  row and note), and the summary still runs.
- The job timeout pairs with the budget: live-smoke's ``noise`` suite gets
  ``timeout-minutes: NOISE_JOB_MINUTES`` (90) = ``JOB_SETUP_S`` (15 min:
  checkout, uv sync, sandbox probe, collection) + ``WALL_BUDGET_S`` (60)
  + ``OVERRUN_S`` (15 min: the target in flight when the budget runs out,
  at least twice the largest target's estimate at K=10), so the summary
  row, the table and the detail note are written before the job is killed.
- Drift: the K baselines of a target run back to back, seconds apart
  (``offsets_s``, ``span_s`` in the row and the spread note, the largest
  span in the detail note), while the engine measures a trial minutes after
  its baseline. Slow drift is under-sampled, so the A/A false-win rate and
  the 95th-percentile difference read optimistic: a floor set from them is
  a lower bound.

The paired path (Step 3, L0; ``LIVE_NOISE_PATH=paired``, which live-smoke's
``noise`` suite exports with the Step 3 noise rule): per target one baseline
and its ``NOISE_CALIBRATION_BLOCKS`` calibration (``GitBaselineRunner``), the
floor raised as the baseline node raises it (``raised_objective``), then
``AA_BLOCKS`` (10) A/A blocks, each the base against a twin worktree ABBA
through ``measure_abab`` (``AaRunner.aa_block``, a calibration block that
keeps its rows), judged as a paired trial by the real judges
(``judge_look``); a would-be keep is confirmed on a fresh block
(``CONFIRM_WINNERS``). Recorded: the single-look false wins of the 130
looks (the gate: at most ``GATE_MAX_WINS``), the kept count, the mean
signed A/A gap and its sign, the floors, and whether row O's gains clear
them. The wall model prices each launch at the profile's plain seconds
(``MEASURED_SLOWDOWN``: the Window 0 run's measured rate was below it).
"""

from __future__ import annotations

import functools
import math
import re
import statistics
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Final, Literal

from e2e.conftest import Isolation, LaunchLog, RepoSnapshot, UserRepo

from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.errors import EngineError
from autonomous_ai_agents.common.models import (
    METRIC_PEAK_RSS_BYTES,
    METRIC_WALL_TIME_S,
    NOISE_FLOOR_MIN,
    Baseline,
    ChangeClass,
    Direction,
    Guardrail,
    GuardrailKind,
    Hypothesis,
    HypothesisSource,
    JudgeOutcome,
    Measurement,
    NoiseCalibration,
    Objective,
    ObjectiveKind,
    Project,
    Trial,
    TrialStatus,
    VerdictOutcome,
    Workload,
)
from autonomous_ai_agents.execution.git import GitWorkspace, repo_fingerprint
from autonomous_ai_agents.execution.measure import AbabMeasured, measure_abab
from autonomous_ai_agents.execution.phase import (
    owned_phases,
    phase_dirs,
    require_dir_name,
)
from autonomous_ai_agents.execution.preflight import GitPreflight
from autonomous_ai_agents.execution.procrun import RunFailure
from autonomous_ai_agents.execution.trial_runner import (
    CALIBRATE_PHASES,
    GitBaselineRunner,
)
from autonomous_ai_agents.optimization.judges import (
    MemoryJudge,
    SpeedJudge,
    default_judges,
    derive_verdict,
    primary_metric,
)
from autonomous_ai_agents.orchestrator.nodes import (
    DEFAULT_RSS_MAX_GROWTH,
    _active_judges,
    _baseline_workload_ids,
    _check_preflight,
    _guardrail_metrics,
    _noise,
    _objective_metrics,
    _require_trustworthy_baseline,
    measurement_violations,
)

from .conftest import LiveRun, make_repo
from .corpus import CORPUS, CorpusRepo
from .discovery import ceil_usd
from .discovery_io import ResultsSink, cells, env_whole, write_markdown
from .oss import OSS_CORPUS, OssRepo, prepare_repo

NOISE_EXPERIMENT: Final = "noise"
NOISE_K_ENV: Final = "LIVE_NOISE_K"
NOISE_K: Final = 6
NOISE_MIN_K: Final = 2  # one ordered pair each way
NOISE_MAX_K: Final = 10
NOISE_REQUESTS_WORST_USD: Final[tuple[float, ...]] = ()  # no Claude request
NOISE_RUN_CAP_USD: Final = ceil_usd(math.fsum(NOISE_REQUESTS_WORST_USD))
NOISE_JOB_MINUTES: Final = 90  # live-smoke's timeout-minutes for "noise"
JOB_SETUP_S: Final = 15 * 60.0  # checkout, uv sync, sandbox probe, collection
OVERRUN_S: Final = 15 * 60.0  # the target in flight when the budget runs out
WALL_BUDGET_S: Final = NOISE_JOB_MINUTES * 60.0 - JOB_SETUP_S - OVERRUN_S
RUNNER_SLOWDOWN: Final = 1.5  # a GitHub runner against the Lead's container
LAUNCH_OVERHEAD_S: Final = 0.5  # reset, sandbox and interpreter start, a launch
BASELINE_OVERHEAD_S: Final = 3.0  # worktree add and cleanup, a baseline
OSS_SETUP_S: Final = 30.0  # depth-1 clone, benchmark commit, preflight
CONTROL_SETUP_S: Final = 5.0  # copy, commit, preflight
CONTROL_RUN_S: Final = 0.7  # the controls ran 0.5-0.7 s locally
QUANTILE: Final = 0.95
_PLAIN: Final = re.compile(r"\((\d+(?:\.\d+)?) s plain\)")
NOISE_PATH_ENV: Final = "LIVE_NOISE_PATH"
AA_BLOCKS: Final = 10  # L0: A/A blocks a repository (spec section 6)
AA_PHASES: Final = ("aa-block", "twin-aa-block")
CONFIRM_ALLOWANCE: Final = 1  # confirmations planned a repository (2.8 %: 0.28)
GATE_MAX_WINS: Final = 1  # single-look false wins allowed of the 130 looks
MEASURED_SLOWDOWN: Final = 1.0  # Window 0: 468 launches in 7 min, setup included
BASELINE_PHASES: Final = frozenset({"preflight", "baseline"})
PAIRED_PHASES: Final = BASELINE_PHASES | set(CALIBRATE_PHASES) | set(AA_PHASES)
ROW_O_GAINS: Final[Mapping[str, float]] = {  # STATUS ledger row O (aimed OSS)
    "tabulate": 0.143, "tomli": 0.133, "markdown": 0.102, "idna": 0.101,
    "sqlparse": 0.040, "mistune": 0.032,
}  # fmt: skip

Kind = Literal["oss", "control"]
NoisePath = Literal["baselines", "paired"]

# ---------------------------------------------------------------------------
# Targets and the plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NoiseTarget:
    """One repository: its workload argv, run time estimate and preparation."""

    name: str
    kind: Kind
    argv: tuple[str, ...]
    run_s: float
    setup_s: float
    prepare: Callable[[Path], UserRepo]


def plain_seconds(profile: str) -> float:
    """The ``(x s plain)`` run time an OSS manifest profile records."""
    found = _PLAIN.search(profile)
    if found is None:
        raise ValueError(f"no '(x s plain)' run time in the profile {profile[:80]!r}")
    return float(found[1])


def oss_target(repo: OssRepo) -> NoiseTarget:
    prepare = functools.partial(prepare_repo, repo)
    run_s = plain_seconds(repo.profile)
    return NoiseTarget(
        repo.name, "oss", repo.workload_argv, run_s, OSS_SETUP_S, prepare
    )


def control_target(repo: CorpusRepo) -> NoiseTarget:
    prepare = functools.partial(make_repo, repo.path)
    argv = repo.workload_argv
    return NoiseTarget(
        repo.name, "control", argv, CONTROL_RUN_S, CONTROL_SETUP_S, prepare
    )


NOISE_TARGETS: Final = (
    *(oss_target(repo) for repo in OSS_CORPUS),
    *(control_target(repo) for repo in CORPUS if repo.kind == "control"),
)


def baseline_runs() -> int:
    """Launches of one baseline: the workload's warm-ups and timed runs."""
    probe = Workload(project_id="noise", name="noise", command=("python",))
    return probe.warmup_runs + max(settings.MIN_RUNS, probe.runs)


def baseline_s(target: NoiseTarget) -> float:
    launch = target.run_s * RUNNER_SLOWDOWN + LAUNCH_OVERHEAD_S
    return baseline_runs() * launch + BASELINE_OVERHEAD_S


def estimate_s(targets: Sequence[NoiseTarget], k: int) -> float:
    return math.fsum(t.setup_s + k * baseline_s(t) for t in targets)


def largest_target_s(targets: Sequence[NoiseTarget] = NOISE_TARGETS) -> float:
    """The slowest single target's estimate at the largest K."""
    return max(estimate_s([t], NOISE_MAX_K) for t in targets)


@dataclass(frozen=True)
class NoisePlan:
    targets: tuple[NoiseTarget, ...]
    k_requested: int
    k: int
    estimate_s: float
    budget_s: float = WALL_BUDGET_S
    path: NoisePath = "baselines"
    blocks: int = 0  # paired: A/A blocks a target
    calibration_blocks: int = 0  # paired: the baseline's calibration
    confirm: bool = False  # paired: a would-be keep re-tested

    @property
    def runs(self) -> int:
        """Live runs: one per target, then the summary."""
        return len(self.targets) + 1

    @property
    def comparisons(self) -> int:
        """Paired: the single looks planned (identical code each)."""
        return len(self.targets) * self.blocks


def noise_need(plan: NoisePlan) -> float:
    """The sum of the caps the suite asks the ledger for."""
    return math.fsum(NOISE_RUN_CAP_USD for _ in range(plan.runs))


def noise_plan(
    environ: Mapping[str, str],
    targets: Sequence[NoiseTarget] = NOISE_TARGETS,
    budget_s: float = WALL_BUDGET_S,
) -> NoisePlan:
    """``$LIVE_NOISE_K`` (2-10, default 6), scaled down to fit ``budget_s``;
    ``$LIVE_NOISE_PATH=paired`` plans the paired path instead."""
    path = environ.get(NOISE_PATH_ENV, "baselines")
    if path == "paired":
        return paired_plan(targets, budget_s)
    if path != "baselines":
        raise ValueError(f"{NOISE_PATH_ENV} must be baselines or paired, got {path!r}")
    requested = env_whole(
        environ, NOISE_K_ENV, NOISE_K, low=NOISE_MIN_K, high=NOISE_MAX_K
    )
    fits = [
        k
        for k in range(NOISE_MIN_K, requested + 1)
        if estimate_s(targets, k) <= budget_s
    ]
    if not fits:
        raise ValueError(
            f"even K={NOISE_MIN_K} needs about "
            f"{estimate_s(targets, NOISE_MIN_K) / 60:.0f} min, past {budget_s / 60:.0f}"
        )
    k = max(fits)
    return NoisePlan(tuple(targets), requested, k, estimate_s(targets, k), budget_s)


def paired_launches(calibration_blocks: int) -> int:
    """One target's launches: the baseline, then calibration, A/A and the
    planned confirmation blocks, each block both sides of a baseline."""
    blocks = calibration_blocks + AA_BLOCKS + CONFIRM_ALLOWANCE
    return baseline_runs() * (1 + 2 * blocks)


def paired_estimate_s(targets: Sequence[NoiseTarget], calibration_blocks: int) -> float:
    launches = paired_launches(calibration_blocks)
    return math.fsum(
        t.setup_s + launches * t.run_s * MEASURED_SLOWDOWN for t in targets
    )


def paired_plan(targets: Sequence[NoiseTarget], budget_s: float) -> NoisePlan:
    """``AA_BLOCKS`` a target under the settings' Step 3 rule, refused when
    the rule is off or the estimate is past ``budget_s``."""
    blocks = settings.NOISE_CALIBRATION_BLOCKS
    if not settings.PAIRED_TRIALS or blocks < 1:
        raise ValueError(
            "the paired path measures the Step 3 rule: PAIRED_TRIALS=true and "
            f"NOISE_CALIBRATION_BLOCKS 1-5, got {settings.PAIRED_TRIALS} and {blocks}"
        )
    found = paired_estimate_s(targets, blocks)
    if found > budget_s:
        raise ValueError(
            f"the paired path needs about {found / 60:.0f} min, past "
            f"{budget_s / 60:.0f}"
        )
    return NoisePlan(
        tuple(targets), 0, 0, found, budget_s, path="paired", blocks=AA_BLOCKS,
        calibration_blocks=blocks, confirm=settings.CONFIRM_WINNERS,
    )  # fmt: skip


# ---------------------------------------------------------------------------
# Arithmetic
# ---------------------------------------------------------------------------


def cv(values: Sequence[float]) -> float | None:
    """Sample stdev over |mean|; ``None`` below two values or at a zero mean."""
    if len(values) < 2 or statistics.fmean(values) == 0:
        return None
    return statistics.stdev(values) / abs(statistics.fmean(values))


def percentile(values: Sequence[float], q: float) -> float:
    """The ``q`` quantile, interpolated linearly between the closest ranks."""
    if not values:
        raise ValueError("a percentile of no values")
    if not 0 <= q <= 1:
        raise ValueError(f"quantile {q} is not in [0, 1]")
    ranked = sorted(values)
    rank = q * (len(ranked) - 1)
    low, high = math.floor(rank), math.ceil(rank)
    return ranked[low] + (ranked[high] - ranked[low]) * (rank - low)


def ordered_pairs(k: int) -> tuple[tuple[int, int], ...]:
    return tuple((i, j) for i in range(k) for j in range(k) if i != j)


def pair_diffs(means: Sequence[float]) -> tuple[float, ...]:
    """|mean_j - mean_i| / |mean_i| for every ordered pair (i's mean not 0)."""
    return tuple(
        abs(means[j] - means[i]) / abs(means[i])
        for i, j in ordered_pairs(len(means))
        if means[i] != 0
    )


# ---------------------------------------------------------------------------
# The A/A test through the engine's own judges
# ---------------------------------------------------------------------------


def runtime_objective(project_id: str) -> Objective:
    """The define node's default objective (no user objective given)."""
    return Objective(
        project_id=project_id,
        kind=ObjectiveKind.runtime,
        metric=METRIC_WALL_TIME_S,
        direction=Direction.minimize,
        min_relative_gain=settings.MIN_RELATIVE_GAIN,
        description="minimize wall time",
    )


def memory_objective(project_id: str) -> Objective:
    return Objective(
        project_id=project_id,
        kind=ObjectiveKind.peak_memory,
        metric=METRIC_PEAK_RSS_BYTES,
        direction=Direction.minimize,
        min_relative_gain=settings.MIN_RELATIVE_GAIN,
        description="minimize peak memory",
    )


def noise_guardrails(project_id: str) -> tuple[Guardrail, ...]:
    """Output equivalence, and the define node's default peak-RSS bound."""
    return (
        Guardrail(
            project_id=project_id,
            kind=GuardrailKind.output_equivalence,
            description="the workload prints the same output",
        ),
        Guardrail(
            project_id=project_id,
            kind=GuardrailKind.metric_bound,
            metric=METRIC_PEAK_RSS_BYTES,
            max_drop=DEFAULT_RSS_MAX_GROWTH,
            direction=Direction.minimize,
            description="peak RSS may not grow (default)",
        ),
    )


def aa_hypothesis(project_id: str) -> Hypothesis:
    return Hypothesis(
        project_id=project_id,
        source=HypothesisSource.playbook,
        title="a-a-control",
        rationale="nothing changed: the base measured again",
        change_class=ChangeClass.efficiency,
        expected_gain=0.0,
        provability=0.5,
        risk=0.0,
    )


def as_trial(hypothesis: Hypothesis, rows: Sequence[Measurement]) -> Trial:
    return Trial(
        hypothesis_id=hypothesis.id,
        round=1,
        status=TrialStatus.measured,
        measurements=tuple(rows),
    )


@dataclass(frozen=True)
class AaCounts:
    pairs: int
    speed_wins: int  # SpeedJudge passed: a false win
    keeps: int  # the whole verdict would ship it
    memory_wins: int  # MemoryJudge passed under a peak-memory objective


def judge_pair(
    base: Baseline, trial: Trial, hypothesis: Hypothesis
) -> tuple[bool, bool]:
    """``trial`` against ``base``: did the real ``SpeedJudge`` pass (a false
    win), and would the whole verdict over the active default judges keep it?"""
    noise_rule = settings.NOISE_MULTIPLIER
    speed = SpeedJudge(noise_multiplier=noise_rule).evaluate(base, trial)
    active = _active_judges(default_judges(noise_rule), base.objectives)
    metrics = _objective_metrics(base.objectives)
    violations = measurement_violations(
        trial.measurements,
        _baseline_workload_ids(base, metrics),
        metrics,
        settings.MIN_RUNS,
        guardrail_metrics=_guardrail_metrics(base.guardrails),
    )
    results = tuple(judge.evaluate(base, trial) for judge in active)
    verdict = derive_verdict(
        trial, hypothesis, results, violations,
        primary_metric=primary_metric(base.objectives),
    )  # fmt: skip
    return speed.outcome is JudgeOutcome.passed, verdict.outcome is VerdictOutcome.keep


def aa_counts(project_id: str, baselines: Sequence[Sequence[Measurement]]) -> AaCounts:
    """Every ordered pair (i, j): baseline j judged as a trial against i."""
    runtime, memory = runtime_objective(project_id), memory_objective(project_id)
    guards = noise_guardrails(project_id)
    lean = MemoryJudge(noise_multiplier=settings.NOISE_MULTIPLIER)
    hypothesis = aa_hypothesis(project_id)
    pairs = ordered_pairs(len(baselines))
    wins = keeps = memory_wins = 0
    for i, j in pairs:
        base = Baseline(
            measurements=tuple(baselines[i]), objectives=(runtime,), guardrails=guards
        )
        trial = as_trial(hypothesis, baselines[j])
        won, kept = judge_pair(base, trial, hypothesis)
        wins += won
        keeps += kept
        lean_base = base.model_copy(update={"objectives": (memory,)})
        memory_wins += lean.evaluate(lean_base, trial).outcome is JudgeOutcome.passed
    return AaCounts(len(pairs), wins, keeps, memory_wins)


# ---------------------------------------------------------------------------
# One repository, the summary, the notes
# ---------------------------------------------------------------------------


def _metric(rows: Sequence[Measurement], metric: str) -> Measurement:
    return next(m for m in rows if m.metric == metric)


def _within(rows: Sequence[Sequence[Measurement]], metric: str) -> float | None:
    found = [
        m.stats.stdev / abs(m.stats.mean)
        for m in (_metric(r, metric) for r in rows)
        if m.stats.mean != 0
    ]
    return statistics.median(found) if found else None


@dataclass(frozen=True)
class RepoNoise:
    name: str
    kind: str
    k_planned: int
    k: int  # trusted baselines
    failures: tuple[str, ...]
    mean_time_s: float | None
    cv_time: float | None  # within a baseline, the median over the K
    cv_mem: float | None
    between_time: float | None  # of the K means
    between_mem: float | None
    floor_median: float | None  # the engine's max(2 CV, MIN_RELATIVE_GAIN)
    noisy: int  # baselines the noisy-host check flagged
    aa: AaCounts
    diffs: tuple[float, ...]
    p95_diff: float | None
    wall_s: float
    offsets_s: tuple[float, ...] = ()  # each trusted baseline's start, from the first
    span_s: float | None = None  # last start minus first: seconds, not minutes

    @property
    def floor_too_low(self) -> bool | None:
        """True when 5 % or more of the A/A differences pass the 2 % floor."""
        if self.p95_diff is None:
            return None
        return self.p95_diff > settings.MIN_RELATIVE_GAIN

    def row(self) -> dict[str, object]:
        return {
            "experiment": NOISE_EXPERIMENT, "kind": self.kind, "repo": self.name,
            "k_planned": self.k_planned, "k": self.k, "failures": list(self.failures),
            "mean_time_s": self.mean_time_s, "cv_time": self.cv_time,
            "cv_mem": self.cv_mem, "between_time": self.between_time,
            "between_mem": self.between_mem, "floor_median": self.floor_median,
            "noisy": self.noisy, "pairs": self.aa.pairs, "aa_wins": self.aa.speed_wins,
            "aa_keeps": self.aa.keeps, "mem_aa_wins": self.aa.memory_wins,
            "p95_diff": self.p95_diff, "floor_too_low": self.floor_too_low,
            "diffs": list(self.diffs), "wall_s": self.wall_s,
            "offsets_s": list(self.offsets_s), "span_s": self.span_s,
        }  # fmt: skip


def summarize_repo(
    name: str,
    kind: str,
    k_planned: int,
    project_id: str,
    baselines: Sequence[Sequence[Measurement]],
    failures: Sequence[str],
    wall_s: float,
    offsets_s: Sequence[float] = (),
) -> RepoNoise:
    times = [_metric(r, METRIC_WALL_TIME_S).stats.mean for r in baselines]
    rss = [_metric(r, METRIC_PEAK_RSS_BYTES).stats.mean for r in baselines]
    objectives = (runtime_objective(project_id),)
    checks = [n for rows in baselines for n in _noise(rows, objectives)]
    floors = [n.floor for n in checks if n.floor is not None]
    diffs = pair_diffs(times)
    return RepoNoise(
        name=name,
        kind=kind,
        k_planned=k_planned,
        k=len(baselines),
        failures=tuple(failures),
        mean_time_s=statistics.fmean(times) if times else None,
        cv_time=_within(baselines, METRIC_WALL_TIME_S),
        cv_mem=_within(baselines, METRIC_PEAK_RSS_BYTES),
        between_time=cv(times),
        between_mem=cv(rss),
        floor_median=statistics.median(floors) if floors else None,
        noisy=sum(n.noisy for n in checks),
        aa=aa_counts(project_id, baselines),
        diffs=diffs,
        p95_diff=percentile(diffs, QUANTILE) if diffs else None,
        wall_s=wall_s,
        offsets_s=tuple(offsets_s),
        span_s=max(offsets_s) - min(offsets_s) if len(offsets_s) >= 2 else None,
    )


def _f(value: float | None, digits: int = 4) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def repo_note(r: RepoNoise) -> str:
    return (
        f"NOISE {r.name}: k {r.k} cv_time {_f(r.cv_time)} cv_mem {_f(r.cv_mem)} "
        f"aa_wins {r.aa.speed_wins}/{r.aa.pairs} p95_diff {_f(r.p95_diff)}"
    )


def spread_note(r: RepoNoise) -> str:
    return (
        f"NOISE spread {r.name}: between_time {_f(r.between_time)} between_mem "
        f"{_f(r.between_mem)} mean_s {_f(r.mean_time_s, 3)} floor_median "
        f"{_f(r.floor_median)} noisy {r.noisy}/{r.k} aa_keeps {r.aa.keeps}/"
        f"{r.aa.pairs} mem_aa_wins {r.aa.memory_wins}/{r.aa.pairs} failed "
        f"{len(r.failures)}/{r.k_planned} wall_s {r.wall_s:.0f} span_s "
        f"{_f(r.span_s, 0)}"
    )


@dataclass(frozen=True)
class NoiseSummary:
    median_cv: float | None
    median_between: float | None
    wins: int
    keeps: int
    memory_wins: int
    pairs: int
    p95_diff: float | None
    too_low: int
    measured: int  # repositories with at least one pair
    span_max_s: float | None = None  # the widest K-baseline span of any repo


def summarize(results: Sequence[RepoNoise]) -> NoiseSummary:
    cvs = [r.cv_time for r in results if r.cv_time is not None]
    betweens = [r.between_time for r in results if r.between_time is not None]
    diffs = [d for r in results for d in r.diffs]
    return NoiseSummary(
        median_cv=statistics.median(cvs) if cvs else None,
        median_between=statistics.median(betweens) if betweens else None,
        wins=sum(r.aa.speed_wins for r in results),
        keeps=sum(r.aa.keeps for r in results),
        memory_wins=sum(r.aa.memory_wins for r in results),
        pairs=sum(r.aa.pairs for r in results),
        p95_diff=percentile(diffs, QUANTILE) if diffs else None,
        too_low=sum(r.floor_too_low is True for r in results),
        measured=sum(r.aa.pairs > 0 for r in results),
        span_max_s=max(spans) if (spans := [r.span_s for r in results
                                             if r.span_s is not None]) else None,
    )  # fmt: skip


def summary_note(s: NoiseSummary) -> str:
    rate = s.wins / s.pairs if s.pairs else None
    return (
        f"NOISE summary: median cv {_f(s.median_cv)}, aa false-win rate {_f(rate)}, "
        f"p95 diff {_f(s.p95_diff)}, floor {settings.MIN_RELATIVE_GAIN:g} too low "
        f"on {s.too_low}/{s.measured} repos"
    )


def detail_note(s: NoiseSummary, plan: NoisePlan, wall_s: float) -> str:
    return (
        f"NOISE summary detail: k {plan.k} (asked {plan.k_requested}), aa wins "
        f"{s.wins}/{s.pairs}, keeps {s.keeps}/{s.pairs}, mem wins {s.memory_wins}/"
        f"{s.pairs}, median between cv {_f(s.median_between)}, estimate "
        f"{plan.estimate_s / 60:.0f} min, wall {wall_s / 60:.0f} min, span max "
        f"{_f(s.span_max_s, 0)} s (floor: a lower bound)"
    )


class NoiseRecorder:
    """Rows to the sink, notes to each run, the table at the end."""

    def __init__(
        self,
        plan: NoisePlan,
        sink: ResultsSink,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.plan, self.sink, self.clock = plan, sink, clock
        self.results: list[RepoNoise] = []
        self.paired: list[PairedNoise] = []
        self.errors: list[tuple[str, str]] = []
        self.skipped: list[str] = []
        self.started = clock()

    def past_budget(self) -> bool:
        """The wall budget is spent: no further target is started."""
        return self.clock() - self.started > self.plan.budget_s

    def record(self, found: RepoNoise, run: LiveRun) -> None:
        self.results.append(found)
        self.sink.write(found.row())
        run.note(repo_note(found))
        run.note(spread_note(found))

    def record_paired(self, found: PairedNoise, run: LiveRun) -> None:
        self.paired.append(found)
        self.sink.write(found.row())
        run.note(paired_note(found))

    def record_error(
        self,
        name: str,
        run: LiveRun,
        error: str,
        measured: Mapping[str, object] | None = None,
    ) -> None:
        """An ``error`` row, with the numbers when a guard failed after them."""
        self.errors.append((name, error))
        row: dict[str, object] = {
            "experiment": NOISE_EXPERIMENT,
            "kind": "error",
            "repo": name,
            "error": error,
        }
        if measured is not None:
            row["measured"] = dict(measured)
        self.sink.write(row)
        run.note(f"NOISE {name}: error {error}")

    def record_skip(self, name: str, run: LiveRun) -> None:
        self.skipped.append(name)
        budget_min = self.plan.budget_s / 60
        self.sink.write({
            "experiment": NOISE_EXPERIMENT, "kind": "skipped", "repo": name,
            "budget_s": self.plan.budget_s, "elapsed_s": self.clock() - self.started,
        })  # fmt: skip
        run.note(f"NOISE {name}: skipped past the wall budget ({budget_min:.0f} min)")

    def summarize(self, run: LiveRun) -> NoiseSummary | PairedSummary:
        if self.plan.path == "paired":
            paired = summarize_paired(self.paired, self.plan.comparisons)
            head: dict[str, object] = {"experiment": NOISE_EXPERIMENT}
            self.sink.write(head | {"kind": "paired-summary"} | asdict(paired) | {
                "wall_s": self.clock() - self.started, "skipped": list(self.skipped)
            })  # fmt: skip
            run.note(paired_summary_note(paired))
            run.note(paired_detail_note(paired))
            return paired
        found = summarize(self.results)
        wall = self.clock() - self.started
        row: dict[str, object] = {"experiment": NOISE_EXPERIMENT, "kind": "summary"}
        row |= asdict(found)
        skipped = list(self.skipped)
        self.sink.write(row | {"k": self.plan.k, "wall_s": wall, "skipped": skipped})
        run.note(summary_note(found))
        run.note(detail_note(found, self.plan, wall))
        return found

    def paired_markdown(self) -> str:
        lines = [
            "## Runner noise, paired (A/A blocks)",
            "",
            "| repo | kind | floor | largest gap | looks | wins | kept | mean gap "
            "| row O | stopped |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
        ]
        for r in self.paired:
            lines.append(cells([
                r.name, r.kind, _f(r.floor), _f(r.largest_gap), len(r.looks), r.wins,
                r.kept, _f(r.mean_gap), r.row_o_clears, r.stopped or "-",
            ]))  # fmt: skip
        for name, error in self.errors:
            lines.append(cells([name, "error", error, *("-",) * 7]))
        for name in self.skipped:
            lines.append(cells([name, "skipped", "wall budget", *("-",) * 7]))
        found = summarize_paired(self.paired, self.plan.comparisons)
        notes = [paired_summary_note(found), "", paired_detail_note(found)]
        return "\n".join([*lines, "", *notes])

    def markdown(self) -> str:
        if self.plan.path == "paired":
            return self.paired_markdown()
        lines = [
            "## Runner noise (A/A)",
            "",
            "| repo | kind | k | mean s | cv time | between | cv mem | floor "
            "| noisy | A/A wins | keeps | p95 diff | failed | span s |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: "
            "| ---: | ---: | ---: | ---: |",
        ]
        for r in self.results:
            lines.append(cells([
                r.name, r.kind, r.k, _f(r.mean_time_s, 3), _f(r.cv_time),
                _f(r.between_time), _f(r.cv_mem), _f(r.floor_median), r.noisy,
                f"{r.aa.speed_wins}/{r.aa.pairs}", f"{r.aa.keeps}/{r.aa.pairs}",
                _f(r.p95_diff), len(r.failures), _f(r.span_s, 0),
            ]))  # fmt: skip
        for name, error in self.errors:
            lines.append(cells([name, "error", error, *("-",) * 11]))
        for name in self.skipped:
            lines.append(cells([name, "skipped", "wall budget", *("-",) * 11]))
        lines += ["", summary_note(summarize(self.results))]
        return "\n".join(lines)

    def finish(self, echo: Callable[[str], None]) -> None:
        write_markdown("Runner noise", self.markdown(), self.sink.environ, echo)


# ---------------------------------------------------------------------------
# The live driver and its guards
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TargetRun:
    """K baselines of one target, the failed ones, the runners' notes, and
    each trusted baseline's start offset from the first baseline's start."""

    user: UserRepo
    before: RepoSnapshot
    project_id: str
    baselines: tuple[tuple[Measurement, ...], ...]
    failures: tuple[str, ...]
    notes: tuple[str, ...]
    wall_s: float
    offsets_s: tuple[float, ...] = ()


class AaRunner(GitBaselineRunner):
    """The real baseline runner plus ``aa_block``: one calibration block
    (``calibrate``'s two fresh worktrees at ``commit``, every workload ABBA
    through ``measure_abab``, the repository fingerprint checked) that keeps
    its rows, in the ``AA_PHASES`` worktrees."""

    def aa_block(
        self, workloads: Sequence[Workload], *, run_id: str, commit: str
    ) -> tuple[AbabMeasured, ...]:
        require_dir_name("run id", run_id)
        sides = [phase_dirs(run_id, name) for name in AA_PHASES]
        before = repo_fingerprint(self._git)
        found: list[AbabMeasured] = []
        failed: RunFailure | None = None
        with owned_phases(self._git, "an A/A block", *sides):
            a, b = (
                self._make_phase(self._git.add_worktree(d.worktree, commit), d)
                for d in sides
            )
            try:
                for workload in workloads:
                    found.append(measure_abab(a, b, workload))
                    self._note("aa", found[-1].notes)
            except RunFailure as failure:
                self._note("aa", failure.notes)
                failed = failure
            self._tampered(before, what="an A/A block")
        if failed is not None:
            raise EngineError(f"an A/A block could not be measured: {failed.reason}")
        return tuple(found)


@dataclass(frozen=True)
class _Connected:
    user: UserRepo
    before: RepoSnapshot
    project_id: str
    workloads: tuple[Workload, ...]
    commit: str | None
    runner: AaRunner
    notes: list[str]


def _connect(
    target: NoiseTarget, root: Path, isolation: Isolation, launches: LaunchLog
) -> _Connected:
    """``target`` prepared at ``root/user``, through the engine's preflight,
    and its baseline runner."""
    user = target.prepare(root / "user")
    before = user.snapshot()
    project = Project(name=target.name, root_path=str(user.path))
    workload = Workload(project_id=project.id, name=target.name, command=target.argv)
    guards = noise_guardrails(project.id)
    mode = isolation.mode
    preflight = GitPreflight(network=mode, fs=mode, run=launches)
    report = preflight.check(project, [workload], guards)
    _check_preflight(report, [workload])
    resolved = project.model_copy(update={"test_command": report.test_command})
    notes: list[str] = []
    git = GitWorkspace(
        user.path, executable=settings.GIT_EXECUTABLE, timeout_s=settings.GIT_TIMEOUT_S
    )
    runner = AaRunner(
        resolved, git=git, network=mode, fs=mode, run=launches, on_note=notes.append
    )
    return _Connected(
        user, before, project.id, tuple(report.workloads), report.head_commit,
        runner, notes,
    )  # fmt: skip


def _trusted(
    found: _Connected, run_id: str, objectives: tuple[Objective, ...]
) -> tuple[Measurement, ...]:
    """One baseline through the baseline node's trust checks (``EngineError``)."""
    rows = found.runner.measure(found.workloads, run_id=run_id, commit=found.commit)
    names = {w.id: w.name for w in found.workloads}
    violations = measurement_violations(
        rows, list(names), (METRIC_WALL_TIME_S,), settings.MIN_RUNS,
        guardrail_metrics=(METRIC_PEAK_RSS_BYTES,),
    )  # fmt: skip
    if violations:
        raise EngineError("; ".join(v.message for v in violations))
    guards = noise_guardrails(found.project_id)
    _require_trustworthy_baseline(rows, objectives, guards, names)
    return rows


def measure_target(
    target: NoiseTarget, root: Path, isolation: Isolation, launches: LaunchLog, k: int
) -> TargetRun:
    """``target`` prepared at ``root/user``, connected, measured K times."""
    started = time.monotonic()
    found = _connect(target, root, isolation, launches)
    objectives = (runtime_objective(found.project_id),)
    baselines: list[tuple[Measurement, ...]] = []
    failures: list[str] = []
    offsets: list[float] = []
    first: float | None = None
    for index in range(1, k + 1):
        at = time.monotonic()
        first = at if first is None else first
        offset = at - first
        try:
            rows = _trusted(found, f"noise-{index}", objectives)
        except EngineError as exc:
            failures.append(f"baseline {index}: {exc}")
            continue
        baselines.append(rows)
        offsets.append(offset)
    wall = time.monotonic() - started
    return TargetRun(
        found.user, found.before, found.project_id, tuple(baselines),
        tuple(failures), tuple(found.notes), wall, tuple(offsets),
    )  # fmt: skip


def summarize_target(target: NoiseTarget, found: TargetRun, k: int) -> RepoNoise:
    return summarize_repo(
        target.name, target.kind, k, found.project_id, found.baselines,
        found.failures, found.wall_s, found.offsets_s,
    )  # fmt: skip


def check_noise_guards(
    run: LiveRun,
    found: TargetRun | PairedRun,
    launches: LaunchLog,
    isolation: Isolation,
) -> None:
    """No request, spend within the cap, every launch sandboxed, only the
    preflight and baseline phases (the paired path: and its calibration and
    A/A blocks), the user's repository untouched. Each message starts with
    the guard's name: it reaches the error row and note."""
    mode = (isolation.mode, isolation.missing)
    assert mode == ("required", None), f"isolation not required: {mode}"
    sent = (len(run.capture.messages()), len(run.records))
    assert sent == (0, 0), f"no request may be sent: {sent}"
    assert run.spent_usd <= run.cap_usd, f"spend over the cap: {run.spent_usd}"
    phases = launches.phases()
    paired = isinstance(found, PairedRun)
    allowed = "preflight" in phases and phases <= (
        PAIRED_PHASES if paired else BASELINE_PHASES
    )
    assert allowed, f"phases outside preflight/baseline: {sorted(phases)}"
    measured = "baseline" in phases or not found.baselines
    assert measured, f"no baseline launch: {sorted(phases)}"
    looked = not isinstance(found, PairedRun) or not found.looks
    assert looked or "aa-block" in phases, f"no A/A block launch: {sorted(phases)}"
    for launch in launches.launches:
        modes = (launch.network, launch.fs)
        assert modes == ("required", "required"), f"unsandboxed launch: {launch}"
        isolated = launch.net_isolated and launch.fs_isolated
        assert isolated, f"launch not isolated: {launch}"
    unchanged = found.user.snapshot() == found.before
    assert unchanged, "user repository changed"
    worktrees = found.user.worktrees()
    assert len(worktrees) == 1, f"worktrees left: {worktrees}"


def run_target(
    target: NoiseTarget,
    run: LiveRun,
    root: Path,
    isolation: Isolation,
    recorder: NoiseRecorder,
) -> RepoNoise | PairedNoise | None:
    """One target measured, its guards, then recorded: a clean row, or an
    ``error`` row (preparation, measurement or a guard; the guard's numbers
    kept under ``measured``, out of the pooled summary) before re-raising.
    Past the wall budget the target is not started: ``skipped``, ``None``.
    The plan's path picks the driver."""
    if recorder.past_budget():
        recorder.record_skip(target.name, run)
        return None
    if recorder.plan.path == "paired":
        return run_paired_target(target, run, root, isolation, recorder)
    launches = LaunchLog()
    try:
        found = measure_target(target, root, isolation, launches, recorder.plan.k)
        result = summarize_target(target, found, recorder.plan.k)
    except BaseException as exc:
        recorder.record_error(target.name, run, f"{type(exc).__name__}: {exc}")
        raise
    try:
        check_noise_guards(run, found, launches, isolation)
    except BaseException as exc:
        recorder.record_error(target.name, run, f"guards: {exc}", result.row())
        raise
    recorder.record(result, run)
    return result


# ---------------------------------------------------------------------------
# L0: the paired path (Step 3, D41)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Look:
    """One A/A block judged as a paired trial."""

    gap: float | None  # (B - A) / A of the wall-time means: below 0, B "faster"
    speed: bool  # SpeedJudge passed: a single-look false win
    keep: bool  # the whole verdict would keep it: confirmation is due
    confirmed: bool | None = None  # the fresh block's verdict; None: none ran


def raised_objective(project_id: str, calibration: NoiseCalibration) -> Objective:
    """The default objective under the calibrated floor, as the baseline
    node raises it; a floor no gain can clear stops the run (``EngineError``)."""
    floor = max(NOISE_FLOOR_MIN, calibration.floor)
    if not floor < 1:
        raise EngineError(f"the noise floor is {floor:.0%}: no gain can be proven")
    base = runtime_objective(project_id)
    least = max(base.min_relative_gain, floor)
    return base.model_copy(update={"min_relative_gain": least})


def judge_look(
    project_id: str, objective: Objective, block: Sequence[AbabMeasured]
) -> Look:
    """B (the twin) judged against its paired A rows, as the judges node
    judges a paired trial (D41 a)."""
    a = tuple(m for pair in block for m in pair.a)
    b = tuple(m for pair in block for m in pair.b)
    base = Baseline(
        measurements=a, objectives=(objective,), guardrails=noise_guardrails(project_id)
    )
    hypothesis = aa_hypothesis(project_id)
    trial = as_trial(hypothesis, b).model_copy(update={"base_measurements": a})
    speed, keep = judge_pair(base, trial, hypothesis)
    mean_a, mean_b = (_metric(r, METRIC_WALL_TIME_S).stats.mean for r in (a, b))
    gap = (mean_b - mean_a) / mean_a if mean_a else None
    return Look(gap, speed, keep)


def aa_looks(
    project_id: str,
    objective: Objective,
    draw: Callable[[str], Sequence[AbabMeasured]],
    blocks: int,
    *,
    confirm: bool,
) -> tuple[Look, ...]:
    """``blocks`` looks; with ``confirm`` a would-be keep is re-tested once on a
    fresh block (D41 b) and holds only if that keeps too."""
    looks: list[Look] = []
    for index in range(1, blocks + 1):
        look = judge_look(project_id, objective, draw(f"noise-aa-{index}"))
        if look.keep and confirm:
            again = judge_look(project_id, objective, draw(f"noise-aa-{index}-confirm"))
            look = replace(look, confirmed=again.keep)
        looks.append(look)
    return tuple(looks)


def kept_count(looks: Sequence[Look]) -> int:
    """Keeps that would ship: confirmed, or standing with confirmation off."""
    return sum(x.keep and x.confirmed is not False for x in looks)


@dataclass(frozen=True)
class PairedRun:
    """One target's calibrated baseline and its looks; ``stopped`` says where
    the engine would have stopped the run."""

    user: UserRepo
    before: RepoSnapshot
    project_id: str
    baselines: tuple[tuple[Measurement, ...], ...]
    floor: float | None
    largest_gap: float | None
    looks: tuple[Look, ...]
    stopped: str | None
    notes: tuple[str, ...]
    wall_s: float
    judged_floor: float | None = None  # the min_relative_gain the looks used


def measure_paired(
    target: NoiseTarget,
    root: Path,
    isolation: Isolation,
    launches: LaunchLog,
    plan: NoisePlan,
) -> PairedRun:
    started = time.monotonic()
    found = _connect(target, root, isolation, launches)
    pid, commit, runner = found.project_id, found.commit, found.runner
    rows: tuple[Measurement, ...] = ()
    calibration: NoiseCalibration | None = None
    looks: tuple[Look, ...] = ()
    stopped: str | None = None
    judged: float | None = None
    try:
        rows = _trusted(found, "noise-paired", (runtime_objective(pid),))
        if commit is None:
            raise EngineError("the noise calibration needs the pinned commit")
        calibration = runner.calibrate(
            found.workloads, run_id="noise-calibrate", commit=commit,
            blocks=plan.calibration_blocks,
        )  # fmt: skip
        objective = raised_objective(pid, calibration)
        judged = objective.min_relative_gain

        def draw(run_id: str) -> tuple[AbabMeasured, ...]:
            return runner.aa_block(found.workloads, run_id=run_id, commit=commit)

        looks = aa_looks(pid, objective, draw, plan.blocks, confirm=plan.confirm)
    except EngineError as exc:
        stopped = str(exc)
    return PairedRun(
        found.user, found.before, pid, (rows,) if rows else (),
        None if calibration is None else calibration.floor,
        None if calibration is None else max(calibration.gaps.values(), default=0.0),
        looks, stopped, tuple(found.notes), time.monotonic() - started, judged,
    )  # fmt: skip


@dataclass(frozen=True)
class PairedNoise:
    name: str
    kind: str
    blocks: int  # planned
    floor: float | None
    largest_gap: float | None
    looks: tuple[Look, ...]
    stopped: str | None
    wall_s: float
    judged_floor: float | None = None  # the looks' min_relative_gain

    @property
    def wins(self) -> int:
        """Would-be keeps: what the gate counts (confirmation is due on them)."""
        return sum(x.keep for x in self.looks)

    @property
    def speed_wins(self) -> int:
        return sum(x.speed for x in self.looks)

    @property
    def kept(self) -> int:
        return kept_count(self.looks)

    @property
    def confirmations(self) -> int:
        return sum(x.confirmed is not None for x in self.looks)

    @property
    def mean_gap(self) -> float | None:
        gaps = [x.gap for x in self.looks if x.gap is not None]
        return statistics.fmean(gaps) if gaps else None

    @property
    def row_o_gain(self) -> float | None:
        return ROW_O_GAINS.get(self.name)

    @property
    def row_o_clears(self) -> bool | None:
        """Whether row O's gain on this library clears its calibrated floor."""
        if self.row_o_gain is None or self.floor is None:
            return None
        return self.row_o_gain > max(settings.MIN_RELATIVE_GAIN, self.floor)

    def row(self) -> dict[str, object]:
        return {
            "experiment": NOISE_EXPERIMENT, "kind": "paired", "repo": self.name,
            "target_kind": self.kind, "blocks": self.blocks, "looks": len(self.looks),
            "floor": self.floor, "judged_floor": self.judged_floor,
            "largest_gap": self.largest_gap, "wins": self.wins,
            "speed_wins": self.speed_wins, "kept": self.kept,
            "confirmations": self.confirmations, "mean_gap": self.mean_gap,
            "gaps": [x.gap for x in self.looks], "stopped": self.stopped,
            "row_o_gain": self.row_o_gain, "row_o_clears": self.row_o_clears,
            "wall_s": self.wall_s,
        }  # fmt: skip


def paired_note(r: PairedNoise) -> str:
    clears = {None: "-", True: "clears", False: "below"}[r.row_o_clears]
    stopped = "" if r.stopped is None else f" stopped {r.stopped[:40]}"
    return (
        f"NOISE paired {r.name}: floor {_f(r.floor)} gap {_f(r.largest_gap)} wins "
        f"{r.wins}/{len(r.looks)} kept {r.kept} mean_gap {_f(r.mean_gap)} row_o "
        f"{clears} wall_s {r.wall_s:.0f}{stopped}"
    )


@dataclass(frozen=True)
class PairedSummary:
    planned: int  # the single looks planned (130)
    looks: int
    wins: int  # single-look false wins: the would-be keeps, what the gate counts
    speed_wins: int  # SpeedJudge passes (Window 0's 2.8 % counted these)
    kept: int  # after confirmation
    mean_gap: float | None  # over every look
    faster: int  # repositories whose mean gap is below 0
    slower: int
    row_o_clears: int
    row_o_total: int
    stopped: int
    gate: Literal["pass", "fail", "incomplete"]


def summarize_paired(results: Sequence[PairedNoise], planned: int) -> PairedSummary:
    gaps = [x.gap for r in results for x in r.looks if x.gap is not None]
    means = [r.mean_gap for r in results if r.mean_gap is not None]
    wins = sum(r.wins for r in results)
    looks = sum(len(r.looks) for r in results)
    row_o = [r.row_o_clears for r in results if r.row_o_clears is not None]
    gate: Literal["pass", "fail", "incomplete"] = "fail"
    if wins <= GATE_MAX_WINS:
        gate = "pass" if looks >= planned else "incomplete"
    return PairedSummary(
        planned, looks, wins, sum(r.speed_wins for r in results),
        sum(r.kept for r in results), statistics.fmean(gaps) if gaps else None,
        sum(m < 0 for m in means), sum(m > 0 for m in means), sum(row_o), len(row_o),
        sum(r.stopped is not None for r in results), gate,
    )  # fmt: skip


def paired_summary_note(s: PairedSummary) -> str:
    return (
        f"NOISE paired summary: single-look wins {s.wins}/{s.looks} (would-be "
        f"keeps; gate <= {GATE_MAX_WINS}: {s.gate}, {s.planned} planned), speed "
        f"passes {s.speed_wins} (Window 0's 2.8 % counted these), kept {s.kept}"
    )


def paired_detail_note(s: PairedSummary) -> str:
    return (
        f"NOISE paired detail: mean gap {_f(s.mean_gap)} (faster {s.faster}, "
        f"slower {s.slower} repos), row O clears {s.row_o_clears}/{s.row_o_total}, "
        f"stopped {s.stopped}"
    )


def run_paired_target(
    target: NoiseTarget,
    run: LiveRun,
    root: Path,
    isolation: Isolation,
    recorder: NoiseRecorder,
) -> PairedNoise:
    """``run_target`` on the paired path: measured, guarded, recorded."""
    launches = LaunchLog()
    plan = recorder.plan
    try:
        found = measure_paired(target, root, isolation, launches, plan)
    except BaseException as exc:
        recorder.record_error(target.name, run, f"{type(exc).__name__}: {exc}")
        raise
    result = PairedNoise(
        target.name, target.kind, plan.blocks, found.floor, found.largest_gap,
        found.looks, found.stopped, found.wall_s, found.judged_floor,
    )  # fmt: skip
    try:
        check_noise_guards(run, found, launches, isolation)
    except BaseException as exc:
        recorder.record_error(target.name, run, f"guards: {exc}", result.row())
        raise
    recorder.record_paired(result, run)
    return result
