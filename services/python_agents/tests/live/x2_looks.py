"""O64-3 (U8a, record-only): every look of an X2 run, as records.

A look is one measuring call the loop makes through its context: a trial
(``runner.run``) or a compound's replay (``runner.replay``), the noise
calibration (``calibrator.calibrate``) and each combiner re-test
(``combiner.combine``: the verdicts' confirmations, then the run combine's
greedy and fallback re-tests, then the review set's). ``tap_looks`` puts a
wrapper around each of the three, as ``FateTap`` does the generator: every
call is handed on as made and its result returned as is; around it the
wrapper takes a ``/proc`` snapshot before and after (``x2_proc``), never
during, so nothing samples inside a timed interval. ``LookLaunches`` (the
loop's ``LaunchLog``) adds each launch's start and end and the RunSample's
wall and CPU seconds, from which ``look_rows`` finds each look's ABBA
window (``measure_abab``'s order, the pair's phases): the A/B span, each
side's warm-up wall time, and per calibration block its gap and per-side sd
(``NoiseCalibration`` keeps only the largest gap). A window counts only when
its timed runs equal the samples the engine recorded (``ab_aligned``; the
calibration's when its largest gap is the engine's), so a retried or failed
attempt is never read as the measured one. The samples themselves come from
the state (a trial's ``base_measurements`` and ``measurements``) or the
combiner's result. One workload a loop (the X2 loop's). No record feeds a
decision: the engine sees the same calls and the same results.

**What a ``/proc`` delta covers** (the owner's ruling, U8a fix round): the
whole wrapped call, not the timed interval, since ``Measurement.samples``
carry no timestamps and no snapshot is taken inside a call (one between an
ABBA and its suite, or between calibration blocks, needs the owner's go).
Each row says so: ``proc_span`` ``"call"`` and ``proc_includes``, the
call's steps in order as the code runs them, each conditional one with its
setting (``TRIAL_CALL``: the worktree, the editor request, capture with the
anti-cheat and quality-reference checks, the commit, the ABBA, quality
scoring, the suite, the counted, scaling and capture runs, a fix retry;
``REPLAY_CALL``: the parents' cherry-pick, its worktree, the same capture,
checks, commit and measurement, no editor and no retry; ``COMBINE_CALL``: the merge, the
ABBA, quality scoring and the suite; the calibration: all its blocks). The harness's own ``ab`` window (``LookLaunches``) stays beside
it, so a reader can set the delta against the timed interval.

**Combine stages** (``combine_stages``): counted back from the final
state's combinations when the combine node completed
(``combine_completed``: a combination, or a combine-phase event). When it
did not and the last combiner call raised, the node was entered and
failed: its calls cannot be told apart from the confirmations before them,
so every combine look is ``unknown``. When it did not and no combiner call
raised, the run ended before the node (every call a confirmation); a node
that raised outside a combiner call after making one reads the same way
(a limit: the state keeps nothing of it).

**Documented limits:**
- ``x2_proc.MAX_PIDS`` (4096): past it the pid listing is cut in
  ``scandir`` order, so a top process may be missed on a crowded host.
- ``x2_proc.FILE_CAP`` (256 KiB): a ``cpuinfo`` past it (some 170 or more
  logical CPUs) is cut, and the CPU count and clocks read low.
- The engine is this process and its descendants: under xdist the other
  workers count as non-engine (the X2 job runs ``-n 0``).
- ``ab.end`` is the last launch's ``LookLaunches`` end, which also holds
  ``LaunchLog``'s own reads after the launch (its HEAD and ``loadavg``), so
  it can sit a few milliseconds past the last timed run.
"""

from __future__ import annotations

import dataclasses
import math
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from e2e.conftest import LaunchLog

from autonomous_ai_agents.common.config import SiteStacks, settings
from autonomous_ai_agents.common.models import (
    METRIC_CPU_TIME_S,
    METRIC_WALL_TIME_S,
    Baseline,
    Combination,
    Hypothesis,
    Measurement,
    NoiseCalibration,
    Project,
    RunPhase,
    RunStats,
    Trial,
    Workload,
)
from autonomous_ai_agents.execution.combine import BASE, TIP, DryMerge
from autonomous_ai_agents.execution.procrun import OutputCaps, RunSample
from autonomous_ai_agents.execution.protocols import (
    CombineMeasured,
    Combiner,
    KeptChange,
)
from autonomous_ai_agents.execution.runner import TrialRunner
from autonomous_ai_agents.execution.sandbox import SandboxPolicy
from autonomous_ai_agents.execution.trial_runner import CALIBRATE_PHASES
from autonomous_ai_agents.orchestrator.combine_node import ConflictProbe
from autonomous_ai_agents.orchestrator.nodes import (
    NodeContext,
    NoiseCalibrator,
    ReplayRunner,
)
from autonomous_ai_agents.orchestrator.state import EngineState

from .corpus import Loop
from .x2_proc import ProcReader, Snapshot, delta

TWIN = "twin-"  # a paired trial's base side: ``twin-<its phase>``
METRICS = (METRIC_WALL_TIME_S, METRIC_CPU_TIME_S)
UNKNOWN = "unknown"  # a combiner call whose stage cannot be told
# What each wrapped call runs (``GitTrialRunner._execute``, ``_attempt``,
# ``_replay``, ``_capture`` and ``_measure``; ``GitCombiner.combine``), in
# order; a step that runs only under a setting names it
MEASURED = [
    "ABBA against the twin (PAIRED_TRIALS; else the trial's runs alone)",
    "quality scoring (a quality check)",
    "suite",
    "counted run per side (OP_COUNT_JUDGE; its units with IDEAS_COUNT_CONTRACT on)",
    "scaling runs (SCALING_JUDGE)",
    "capture launch per side (SHADOW_VERIFY on)",
]
CAPTURE = ["capture and anti-cheat checks (quality references among them)", "commit"]
TRIAL_CALL = [
    "worktree at the base", "editor request", *CAPTURE, *MEASURED,
    "one fix retry or re-parse of the edit onward (EDITOR_FIX_RETRIES)",
]  # fmt: skip
REPLAY_CALL = ["cherry-pick of the parents", "worktree at the cherry-picked tree",
               *CAPTURE, *MEASURED]  # fmt: skip
COMBINE_CALL = ["merge", "ABBA (when a change applied)",
                "quality scoring (a quality check)", "suite"]  # fmt: skip
INCLUDES: Mapping[str, list[str]] = {"trial": TRIAL_CALL, "replay": REPLAY_CALL,
                                     "calibration": ["all blocks"]}  # fmt: skip
Row = dict[str, object]


@dataclass(frozen=True)
class LaunchTime:
    phase: str
    start: float
    end: float
    wall_s: float  # the RunSample's, as the measurement records it
    cpu_s: float


class LookLaunches(LaunchLog):
    """``LaunchLog`` with each launch's clock span and wall and CPU seconds
    in ``timed`` (a failed launch is the inner's to record)."""

    def __init__(self, shared: Path | None = None, test: str = "", *,
                 clock: Callable[[], float] = time.time) -> None:  # fmt: skip
        super().__init__(shared, test)
        self.timed: list[LaunchTime] = []
        self._clock = clock

    def __call__(self, argv: Sequence[str], cwd: Path, env: Mapping[str, str],
                 sandbox: SandboxPolicy, timeout_s: float, caps: OutputCaps, *,
                 fresh_dirs: Sequence[Path] = ()) -> RunSample:  # fmt: skip
        start = self._clock()
        sample = super().__call__(argv, cwd, env, sandbox, timeout_s, caps, fresh_dirs=fresh_dirs)  # fmt: skip
        self.timed.append(LaunchTime(self.launches[-1].phase, start, self._clock(),
                                     sample.wall_ns / 1e9, sample.utime + sample.stime))  # fmt: skip
        return sample


@dataclass
class Look:
    kind: str  # trial, replay, calibration, combine
    before: Snapshot
    first: int  # ``LookLaunches.timed`` index range
    hypothesis_id: str | None = None
    offered: tuple[str, ...] = ()  # combine: the trial ids offered
    last: int = 0
    after: Snapshot | None = None
    trial_id: str | None = None
    measured: CombineMeasured | None = None
    calibration: NoiseCalibration | None = None
    error: str | None = None  # the exception's class, if the call raised


@dataclass
class LookLog:
    proc: ProcReader
    launches: LookLaunches | None = None
    machine: Row | None = None
    warmups: int = 1
    runs: int = 5
    looks: list[Look] = field(default_factory=list)

    def _count(self) -> int:
        return 0 if self.launches is None else len(self.launches.timed)

    @contextmanager
    def look(self, kind: str, *, hypothesis_id: str | None = None,
             offered: tuple[str, ...] = ()) -> Iterator[Look]:  # fmt: skip
        one = Look(kind, self.proc.snapshot(), self._count(), hypothesis_id, offered)
        try:
            yield one
        except BaseException as exc:
            one.error = type(exc).__name__
            raise
        finally:
            one.last, one.after = self._count(), self.proc.snapshot()
            self.looks.append(one)

    def proc_seconds(self) -> float:
        return round(math.fsum(s.seconds for one in self.looks
                               for s in (one.before, one.after) if s is not None), 4)  # fmt: skip


@dataclass
class LookRunner:
    inner: TrialRunner
    log: LookLog

    def run(self, hypothesis: Hypothesis, workloads: Sequence[Workload],
            baseline: Baseline, **kwargs: Any) -> Trial:  # fmt: skip
        with self.log.look("trial", hypothesis_id=hypothesis.id) as one:
            trial = self.inner.run(hypothesis, workloads, baseline, **kwargs)
            one.trial_id = trial.id
        return trial


@dataclass
class LookReplayRunner(LookRunner):
    """A ``ReplayRunner`` still (``NodeContext`` and the compound need one)."""

    def replay(self, hypothesis: Hypothesis, parents: Sequence[Trial],
               workloads: Sequence[Workload], baseline: Baseline, **kwargs: Any) -> Trial:  # fmt: skip
        with self.log.look("replay", hypothesis_id=hypothesis.id) as one:
            inner = cast(ReplayRunner, self.inner)
            trial = inner.replay(hypothesis, parents, workloads, baseline, **kwargs)
            one.trial_id = trial.id
        return trial


@dataclass
class LookCalibrator:
    inner: NoiseCalibrator
    log: LookLog

    def calibrate(
        self, workloads: Sequence[Workload], **kwargs: Any
    ) -> NoiseCalibration:
        with self.log.look("calibration") as one:
            found = self.inner.calibrate(workloads, **kwargs)
            one.calibration = found
        return found


@dataclass
class LookCombiner:
    inner: Combiner
    log: LookLog

    @property
    def last_notes(self) -> tuple[str, ...]:  # what the nodes read, if any
        return tuple(map(str, getattr(self.inner, "last_notes", ())))

    def combine(self, run_id: str, project: Project, base_commit: str,
                kept: Sequence[KeptChange], workloads: Sequence[Workload],
                **kwargs: Any) -> CombineMeasured:  # fmt: skip
        with self.log.look("combine", offered=tuple(k.trial_id for k in kept)) as one:
            found = self.inner.combine(run_id, project, base_commit, kept, workloads, **kwargs)  # fmt: skip
            one.measured = found
        return found


@dataclass
class LookProbe(LookCombiner):
    """A ``ConflictProbe`` still (S2's dry merge is git only: no look)."""

    @property
    def site_stacks(self) -> SiteStacks:
        return cast(ConflictProbe, self.inner).site_stacks

    def dry_merge(self, project: Project, base_commit: str,
                  kept: Sequence[KeptChange]) -> DryMerge:  # fmt: skip
        return cast(ConflictProbe, self.inner).dry_merge(project, base_commit, kept)


def tap_context(ctx: NodeContext, log: LookLog) -> NodeContext:
    """``ctx`` with its runner, calibrator and combiner behind look
    wrappers, each still a ``ReplayRunner`` or ``ConflictProbe`` when its
    inner one is (the nodes test both)."""
    runner, combiner, calibrator = ctx.runner, ctx.combiner, ctx.calibrator
    looked = LookReplayRunner if isinstance(runner, ReplayRunner) else LookRunner
    probe = LookProbe if isinstance(combiner, ConflictProbe) else LookCombiner
    return dataclasses.replace(
        ctx, runner=looked(runner, log),
        calibrator=None if calibrator is None else LookCalibrator(calibrator, log),
        combiner=None if combiner is None else probe(combiner, log),
    )  # fmt: skip


def tap_looks(loop: Loop, proc: ProcReader, environ: Mapping[str, str]) -> tuple[Loop, LookLog | None]:  # fmt: skip
    """``loop`` through ``tap_context`` and the looks' log (the run's
    ``machine`` read now); ``loop`` itself and ``None`` when its context is
    no ``NodeContext`` (a fake loop)."""
    ctx = getattr(loop, "context", None)
    if not isinstance(ctx, NodeContext):
        return loop, None
    launches = loop.launches if isinstance(loop.launches, LookLaunches) else None
    log = LookLog(proc, launches, proc.machine(environ), loop.workload.warmup_runs,
                  max(settings.MIN_RUNS, loop.workload.runs))  # fmt: skip
    return dataclasses.replace(loop, context=tap_context(ctx, log)), log


# ---------------------------------------------------------------------------
# The rows
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Window:
    """One ABBA of the two phases: per side its warm-ups, then its timed runs."""

    launches: tuple[LaunchTime, ...]
    a: str
    b: str
    warmups: int

    def side(self, phase: str) -> list[LaunchTime]:
        return [t for t in self.launches if t.phase == phase]

    def timed(self, phase: str, cpu: bool = False) -> list[float]:
        return [t.cpu_s if cpu else t.wall_s for t in self.side(phase)[self.warmups :]]

    def warm(self) -> dict[str, list[float]]:
        return {k: [t.wall_s for t in self.side(p)[: self.warmups]]
                for k, p in (("A", self.a), ("B", self.b))}  # fmt: skip

    def span(self) -> Row:
        return {"start": self.launches[0].start, "end": self.launches[-1].end,
                "warmup_wall_s": self.warm()}  # fmt: skip


def windows(span: Sequence[LaunchTime], a: str, b: str, warmups: int, runs: int,
            *, every: bool = False) -> list[Window]:  # fmt: skip
    """Each run of ``a``/``b`` launches in ABBA order, non-overlapping, or
    with ``every`` at each offset (the pattern repeats, so a cut-off attempt
    followed by a whole one also reads as one: the samples decide)."""
    mine = [t for t in span if t.phase in (a, b)]
    want = [
        p for i in range(warmups + runs) for p in ((a, b) if i % 2 == 0 else (b, a))
    ]
    found, k = [], 0
    while want and k + len(want) <= len(mine):
        part = mine[k : k + len(want)]
        if [t.phase for t in part] == want:
            found.append(Window(tuple(part), a, b, warmups))
            k += 1 if every else len(want)
        else:
            k += 1
    return found


def _side(rows: Sequence[Measurement]) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for m in rows:
        if m.metric in METRICS:
            out.setdefault(m.metric, list(m.samples))
    return out


def _pairs(kind: str, span: Sequence[LaunchTime]) -> list[tuple[str, str]]:
    """The (A, B) phases of a trial's (``twin-<phase>``, ``<phase>``) or a
    combiner re-test's ABBA (the calibration's are ``_blocks``')."""
    if kind in ("trial", "replay"):
        phases = {t.phase for t in span}
        return sorted((p, p[len(TWIN):]) for p in phases
                      if p.startswith(TWIN) and p[len(TWIN):] in phases)  # fmt: skip
    return [(BASE, TIP)]


def _ab(log: LookLog, one: Look, kind: str, sides: Mapping[str, Mapping[str, list[float]]] | None) -> Row:  # fmt: skip
    """The look's measured ABBA window: the one whose timed walls are the
    engine's samples; ``ab_aligned`` ``None`` with nothing to align."""
    want = (None, None) if sides is None else (
        sides["A"].get(METRIC_WALL_TIME_S), sides["B"].get(METRIC_WALL_TIME_S))  # fmt: skip
    if log.launches is None or want[0] is None or want[1] is None:  # unpaired too
        return {"ab": None, "ab_aligned": None}
    span = log.launches.timed[one.first : one.last]
    for a, b in _pairs(kind, span):
        for w in reversed(windows(span, a, b, log.warmups, log.runs, every=True)):
            if (w.timed(a), w.timed(b)) == want:
                return {"ab": w.span(), "ab_aligned": True}
    return {"ab": None, "ab_aligned": False}


def _blocks(log: LookLog, one: Look) -> Row:
    """Each calibration block: its span, warm-ups, samples, gap (the engine's
    ``|A - A'| / max``) and per-side sd; aligned when there are as many as
    the calibration ran and the largest gap is its own."""
    if log.launches is None:
        return {"blocks": None, "ab_aligned": None}
    a, b = CALIBRATE_PHASES
    found = windows(
        log.launches.timed[one.first : one.last], a, b, log.warmups, log.runs
    )
    rows, gaps = [], []
    for n, w in enumerate(found, 1):
        sa, sb = (RunStats.from_samples(w.timed(p), unit="s") for p in (a, b))
        top = max(sa.mean, sb.mean)
        gaps.append(abs(sa.mean - sb.mean) / top if top > 0 else 0.0)
        rows.append({"block": n, **w.span(), "gap": gaps[-1],
                     "sd": {"A": sa.stdev, "B": sb.stdev},
                     "samples": {s: {METRIC_WALL_TIME_S: w.timed(p),
                                     METRIC_CPU_TIME_S: w.timed(p, cpu=True)}
                                 for s, p in (("A", a), ("B", b))}})  # fmt: skip
    cal = one.calibration
    aligned = (cal is not None and len(found) == cal.blocks
               and math.isclose(max(gaps), max(cal.gaps.values(), default=0.0)))  # fmt: skip
    return {"blocks": rows, "ab_aligned": aligned}


def combine_completed(st: EngineState | None) -> bool:
    """Whether the combine node's delta landed: a combination, or one of the
    events it always announces (``nodes.combine``: at least one)."""
    if st is None:
        return False
    if st.get("combination") is not None or st.get("review_combination") is not None:
        return True
    return any(e.phase is RunPhase.combine for e in st.get("events", []))


def combine_stages(n: int, run: Combination | None, review: Combination | None,
                   *, completed: bool, raised: bool) -> list[str]:  # fmt: skip
    """Each combiner call's stage, in order: the run combine's greedy and
    fallback re-tests, then the review set's, end the calls (the combine
    node); every earlier one is a verdicts' confirmation. A combine node
    that did not complete is entered and failed when the last call
    ``raised`` (every call ``UNKNOWN``), else never entered (every call a
    confirmation); fewer calls than the combinations account for leave
    every call ``UNKNOWN``."""

    def one(c: Combination | None, kind: str) -> list[str]:
        return [] if c is None else [f"{kind}greedy", *([f"{kind}fallback"] * (c.fallback_trial_id is not None))]  # fmt: skip

    tail = [*one(run, ""), *one(review, "review_")]
    if not completed:
        return [UNKNOWN if raised else "confirm"] * n
    if n < len(tail):
        return [UNKNOWN] * n
    return ["confirm"] * (n - len(tail)) + tail


def look_rows(log: LookLog, st: EngineState | None) -> list[Row]:
    """One row per look, in call order (module docstring)."""
    trials = {} if st is None else {t.id: t for t in st["trials"]}
    owner = {t.id: t.hypothesis_id for t in trials.values()}
    combines = [one for one in log.looks if one.kind == "combine"]
    n, raised = len(combines), bool(combines) and combines[-1].error is not None
    stages = iter(combine_stages(n, None if st is None else st.get("combination"),
                                 None if st is None else st.get("review_combination"),
                                 completed=combine_completed(st), raised=raised))  # fmt: skip
    rows: list[Row] = []
    for k, one in enumerate(log.looks, 1):
        kind = next(stages) if one.kind == "combine" else one.kind
        trial = trials.get(one.trial_id or "")
        rows_a, rows_b = ((one.measured.baseline, one.measured.combined) if one.measured
                          else (trial.base_measurements, trial.measurements) if trial
                          else ((), ()))  # fmt: skip
        sides = {"A": _side(rows_a), "B": _side(rows_b)}
        measured = sides if sides["A"] or sides["B"] else None
        after = one.after or one.before
        rows.append({
            "look": k, "kind": kind, "trial_id": one.trial_id,
            "hypothesis_id": one.hypothesis_id,
            "offered": [owner.get(t, t) for t in one.offered],
            "start": one.before.time, "end": after.time, "error": one.error,
            "samples": measured,
            **(_blocks(log, one) if kind == "calibration" else _ab(log, one, kind, measured)),
            "proc_span": "call", "proc_includes": list(INCLUDES.get(one.kind, COMBINE_CALL)),
            "proc": {"before": one.before.summary(), "after": after.summary(),
                     **delta(one.before, after, log.proc.pid)},
        })  # fmt: skip
    return rows
