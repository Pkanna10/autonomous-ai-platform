"""The engine side of the offline replays (``combine-replay``, ``combine-order``).

``EngineMeasurer`` measures through the engine's own functions (``make_nodes``'
connect, define, baseline and profile; the combine node's re-test) on the
repository as the X2 run built it, under the X2 arms' measurement settings
(``REPLAY_SETTINGS``, ``check_settings``); ``TimedRun`` and ``TimedCalibrator``
time every launch and the calibration. Split out of ``combine_replay`` (O65
item 2) so both suites measure one way; see that module for the design.
"""

from __future__ import annotations

import functools
import math
import shutil
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from e2e.conftest import Isolation, LaunchLog, RepoSnapshot, UserRepo

from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.common.errors import EngineError
from autonomous_ai_agents.common.models import (
    METRIC_WALL_TIME_S,
    Baseline,
    Hypothesis,
    NoiseCalibration,
    Project,
    Trial,
    Workload,
)
from autonomous_ai_agents.execution.combine import BASE, TIP, GitCombiner
from autonomous_ai_agents.execution.git import GitWorkspace
from autonomous_ai_agents.execution.measure import (
    UNKNOWN,
    RunOnce,
    baseline_test_count,
    classify_runner,
)
from autonomous_ai_agents.execution.preflight import PHASE as PREFLIGHT_PHASE
from autonomous_ai_agents.execution.preflight import GitPreflight
from autonomous_ai_agents.execution.procrun import OutputCaps, RunSample
from autonomous_ai_agents.execution.profiler import PHASE as PROFILE_PHASE
from autonomous_ai_agents.execution.profiler import CProfiler
from autonomous_ai_agents.execution.protocols import KeptChange, TrialBrief
from autonomous_ai_agents.execution.sandbox import SandboxPolicy
from autonomous_ai_agents.execution.trial_runner import (
    BASELINE_PHASE,
    CALIBRATE_PHASES,
    GitBaselineRunner,
)
from autonomous_ai_agents.optimization.anticheat import DEFAULT_PROTECTED_PATTERNS
from autonomous_ai_agents.optimization.judges import default_judges
from autonomous_ai_agents.orchestrator.combine_node import (
    CombineRules,
    CombineTarget,
    Retest,
    _retest,
    retest_one,
)
from autonomous_ai_agents.orchestrator.nodes import (
    NodeContext,
    NodeFn,
    NoiseCalibrator,
    _combine_rules,
    make_nodes,
)
from autonomous_ai_agents.orchestrator.state import EngineState, initial_state
from autonomous_ai_agents.persistence.repository import InMemoryRepository

from .conftest import LiveRun
from .oss import (
    PRODUCTION,
    CloneRefusedError,
    GitPolicy,
    OssRepo,
    _Git,
    _scratch_git,
    prepare_repo,
)
from .replay_archive import IntegrityError, _fit
from .x2_patches import safe_name

REPLAY_PHASES: Final = frozenset({
    PREFLIGHT_PHASE, BASELINE_PHASE, *CALIBRATE_PHASES, PROFILE_PHASE, TIP, BASE,
})  # fmt: skip
REPLAY_SETTINGS: Final[Mapping[str, object]] = {
    # ci.yml's step3 noise rule, as the ideas-x2 suite exports it ...
    "PAIRED_TRIALS": True, "CONFIRM_WINNERS": True, "NOISE_CALIBRATION_BLOCKS": 3,
    # ... and ideas_x2.SHARED's op-count judge; X2-D and X2-P set no other
    # measurement key (the scaling judge and the site stacks at their default)
    "OP_COUNT_JUDGE": True, "SCALING_JUDGE": False, "SITE_STACKS": "off",
    # every other key the measurement reads, at the default both arms ran
    "MIN_RUNS": 5, "NOISE_MULTIPLIER": 2.0, "NOISE_GAP_MULTIPLIER": 2.0,
    "MIN_RELATIVE_GAIN": 0.02, "DEFAULT_OUTPUT_CHECK": True, "SHADOW_VERIFY": "off",
    "TEST_TIMEOUT_S": 900.0,
}  # fmt: skip


@dataclass(frozen=True)
class BaselineLook:
    """The baseline node's result: the wall-time objective's floor as the
    judges use it (``max(user value, NOISE_FLOOR_MIN, calibrated floor)``),
    the calibration's own floor and largest gap, its seconds, the suite's
    passing count."""

    floor: float | None
    calibrated: float | None
    largest_gap: float | None
    calibration_s: float | None
    tests: int | None


@dataclass(frozen=True)
class ProfileLook:
    ok: bool  # ran and found a hotspot
    hotspots: int
    notes: int  # the profile node's skip notes
    error: str | None


@dataclass(frozen=True)
class RetestLook:
    """One ``retest_one``: the primary judge's gain and floor, the verdict,
    whether it holds, the suite's judge and count, the suite's seconds."""

    applied: int
    gain: float | None
    floor: float | None
    outcome: str
    holds: bool
    reason: str
    tests: str | None
    tests_counted: int | None
    tests_s: float | None
    notes: tuple[str, ...]
    rows: bool = True  # the combiner's A and B rows are there (no RunFailure)

    @property
    def measured_tip(self) -> bool:
        """The one tip change applied and measured: else not a verdict at all."""
        return self.applied == 1 and self.rows

    @classmethod
    def of(cls, found: Retest, primary: str | None, tests_s: float | None,
           notes: Sequence[str]) -> RetestLook:  # fmt: skip
        results = found.verdict.judge_results
        gain = next((j for j in results if j.metric == primary), None)
        suite = next((j for j in results if j.judge == "tests"), None)
        return cls(
            len(found.measured.applied), None if gain is None else gain.gain,
            None if gain is None else gain.noise_floor, found.verdict.outcome.value,
            found.holds, _fit(found.reason), None if suite is None else suite.outcome.value,
            baseline_test_count(found.measured.combined), tests_s, tuple(map(_fit, notes)),
            bool(found.measured.baseline) and bool(found.measured.combined),
        )  # fmt: skip


# ---------------------------------------------------------------------------
# The timing seams
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Span:
    suite: bool  # a pytest or unittest launch: the project's suite
    seconds: float


class TimedRun:
    """A ``RunOnce`` that hands every launch to ``inner`` (the
    ``LaunchLog``) and times it, failed launches included."""

    def __init__(
        self, inner: RunOnce, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.inner, self.clock = inner, clock
        self.spans: list[Span] = []

    def __call__(self, argv: Sequence[str], cwd: Path, env: Mapping[str, str],
                 sandbox: SandboxPolicy, timeout_s: float, caps: OutputCaps, *,
                 fresh_dirs: Sequence[Path] = ()) -> RunSample:  # fmt: skip
        at = self.clock()
        try:
            return self.inner(
                argv, cwd, env, sandbox, timeout_s, caps, fresh_dirs=fresh_dirs
            )
        finally:
            self.spans.append(Span(classify_runner(argv) != UNKNOWN, self.clock() - at))

    def suite_seconds(self, since: int) -> float | None:
        """The suite launches' seconds from span ``since`` on; ``None``: none."""
        found = [s.seconds for s in self.spans[since:] if s.suite]
        return math.fsum(found) if found else None


@dataclass
class TimedCalibrator:
    """The baseline node's calibrator, timed (``seconds`` summed over calls)."""

    inner: NoiseCalibrator
    clock: Callable[[], float] = time.monotonic
    seconds: float | None = None

    def calibrate(self, workloads: Sequence[Workload], *, run_id: str, commit: str,
                  blocks: int) -> NoiseCalibration:  # fmt: skip
        at = self.clock()
        try:
            return self.inner.calibrate(
                workloads, run_id=run_id, commit=commit, blocks=blocks
            )
        finally:
            self.seconds = (self.seconds or 0.0) + self.clock() - at


# ---------------------------------------------------------------------------
# The engine measurer
# ---------------------------------------------------------------------------

Prepare = Callable[[Path], UserRepo]


class _NoTrials:
    """The context's trial runner: the replay runs no trial."""

    def run(self, hypothesis: Hypothesis, workloads: Sequence[Workload],
            baseline: Baseline, *, round: int, branch: str, budget_usd: float,
            brief: TrialBrief) -> Trial:  # fmt: skip
        raise AssertionError("the combine replay runs no trial")


def commit_patch(user: UserRepo, patch: Path, ref: str, message: str, *,
                 policy: GitPolicy = PRODUCTION,
                 environ: Mapping[str, str] | None = None) -> str:  # fmt: skip
    """``patch`` applied to ``user.base`` as a new commit under ``ref``,
    through a scratch index: nothing checked out moves."""
    scratch = Path(tempfile.mkdtemp(prefix="replay-tip-"))
    try:
        with _scratch_git(user.path, policy, environ) as git:
            env = {**git.env, "GIT_INDEX_FILE": str(scratch / "index")}
            staged = _Git(user.path, env, policy)
            staged("read-tree", user.base)
            try:
                staged("apply", "--cached", "--", str(patch))
            except CloneRefusedError as exc:
                raise IntegrityError(
                    f"the archived patch does not apply: {exc}"
                ) from None
            tree = staged("write-tree")
            tip = git("commit-tree", tree, "-p", user.base, "-m", message)
            git("update-ref", ref, tip)
            return tip
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _merge(state: EngineState, delta: Mapping[str, object]) -> EngineState:
    merged = cast(dict[str, Any], dict(state))
    for key, value in delta.items():
        merged[key] = (
            [*merged[key], *cast(list[object], value)] if key == "events" else value
        )
    return cast(EngineState, merged)


class EngineMeasurer:
    """The real ``Measurer``: ``repo`` prepared at ``root/user``, the
    engine's nodes and the combine node's re-test (module docstring); every
    launch through ``launches`` and timed by ``timed``."""

    def __init__(self, repo: OssRepo, root: Path, isolation: Isolation, *, run_id: str,
                 prepare: Prepare | None = None, policy: GitPolicy = PRODUCTION,
                 environ: Mapping[str, str] | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:  # fmt: skip
        self.repo, self.root, self.isolation, self.run_id = (
            repo,
            root,
            isolation,
            run_id,
        )
        self._prepare: Prepare = prepare or functools.partial(
            prepare_repo, repo, policy=policy, environ=environ
        )
        self.policy, self.environ, self.clock = policy, environ, clock
        self.launches = LaunchLog()
        self.timed = TimedRun(self.launches, clock)
        self._user: UserRepo | None = None
        self._before: RepoSnapshot | None = None
        self._state: EngineState | None = None
        self._ctx: NodeContext | None = None
        self._calibrator: TimedCalibrator | None = None
        self.nodes: dict[str, NodeFn] = {}

    @property
    def user(self) -> UserRepo:
        if self._user is None:
            raise AssertionError("the user's repository is not prepared")
        return self._user

    def _ready(self) -> tuple[EngineState, NodeContext]:
        if self._state is None or self._ctx is None:
            raise AssertionError("the replay is not connected")
        return self._state, self._ctx

    def prepare(self) -> str:
        """The repository at ``root/user``; ``root`` made first (the clone
        refuses a destination with no parent directory)."""
        self.root.mkdir(parents=True, exist_ok=True)
        self._user = self._prepare(self.root / "user")
        return self._user.base

    def commit_tip(self, patch: Path, label: str) -> str:
        return commit_patch(self.user, patch, f"refs/replay/{safe_name(label)}",
                            f"replay: {label}", policy=self.policy, environ=self.environ)  # fmt: skip

    def _context(self, project: Project) -> NodeContext:
        """``factory.build_context``'s measurement pieces, no transport."""
        mode = self.isolation.mode
        git = GitWorkspace(Path(project.root_path), executable=settings.GIT_EXECUTABLE,
                           timeout_s=settings.GIT_TIMEOUT_S)  # fmt: skip
        runner = GitBaselineRunner(project, git=git, network=mode, fs=mode, run=self.timed,
                                   count_ops=settings.OP_COUNT_JUDGE,
                                   scaling=settings.SCALING_JUDGE)  # fmt: skip
        blocks = settings.NOISE_CALIBRATION_BLOCKS
        self._calibrator = TimedCalibrator(runner, self.clock) if blocks else None
        judges = default_judges(settings.NOISE_MULTIPLIER, op_count=settings.OP_COUNT_JUDGE,
                                scaling=settings.SCALING_JUDGE)  # fmt: skip
        return NodeContext(
            runner=_NoTrials(), baseline_runner=runner, judges=judges,
            repository=InMemoryRepository(),
            preflight=GitPreflight(executable=settings.GIT_EXECUTABLE,
                                   protected=DEFAULT_PROTECTED_PATTERNS, network=mode,
                                   fs=mode, run=self.timed),
            profiler=CProfiler(project, git=git, network=mode, fs=mode, run=self.timed),
            combiner=GitCombiner(git=git, network=mode, fs=mode, run=self.timed),
            default_output_check=settings.DEFAULT_OUTPUT_CHECK,
            calibrator=self._calibrator, calibration_blocks=blocks,
            confirm_winners=settings.CONFIRM_WINNERS,
        )  # fmt: skip

    def connect(self) -> None:
        """The snapshot, then the connect and define nodes; the context bound
        to the project the preflight resolved, as the factory's is."""
        user = self.user
        self._before = user.snapshot()
        project = self.repo.project(user.path)
        state = initial_state(project, [self.repo.workload(project)],
                              self.repo.corpus.objectives(project),
                              self.repo.corpus.guardrails(project), run_id=self.run_id)  # fmt: skip
        state = _merge(state, make_nodes(self._context(project))["connect"](state))
        self._ctx = self._context(state["project"])
        self.nodes = make_nodes(self._ctx)
        self._state = _merge(state, self.nodes["define"](state))

    def baseline(self) -> BaselineLook:
        state, _ = self._ready()
        self._state = state = _merge(state, self.nodes["baseline"](state))
        measured = cast(Baseline, state["baseline"])
        wall = [
            o.min_relative_gain
            for o in measured.objectives
            if o.metric == METRIC_WALL_TIME_S
        ]
        calibration = measured.calibration
        return BaselineLook(
            wall[0] if wall else None, None if calibration is None else calibration.floor,
            None if calibration is None else max(calibration.gaps.values(), default=0.0),
            None if self._calibrator is None else self._calibrator.seconds,
            baseline_test_count(measured.measurements),
        )  # fmt: skip

    def profile(self) -> ProfileLook:
        """The profile node on the base; a refusal is recorded, not raised."""
        state, _ = self._ready()
        try:
            delta = self.nodes["profile"](state)
        except EngineError as exc:
            return ProfileLook(False, 0, 0, _fit(f"{type(exc).__name__}: {exc}"))
        hotspots = len(cast(list[object], delta["hotspots"]))
        notes = len(cast(list[object], delta["events"])) - 1  # one announce, then skips
        return ProfileLook(hotspots > 0, hotspots, notes, None)

    def _rules(self, look: str) -> tuple[CombineTarget, CombineRules, GitCombiner]:
        """The combine node's target and rules (``_combine_set``) for ``look``."""
        state, ctx = self._ready()
        measured = cast(Baseline, state["baseline"])
        run_id = f"{self.run_id}-{look}"
        target = CombineTarget(
            run_id=run_id, project=state["project"], base_commit=str(state["base_commit"]),
            workloads=tuple(state["workloads"]), branch=f"{ctx.branch_prefix}run-{run_id}",
            round=1, quality_files=measured.quality_files,
        )  # fmt: skip
        return target, _combine_rules(ctx, measured), cast(GitCombiner, ctx.combiner)

    def retest(self, look: str, change: KeptChange) -> RetestLook:
        """``retest_one`` as the combine node calls it (``_combine_set``)."""
        target, rules, combiner = self._rules(look)
        mark = len(self.timed.spans)
        found = retest_one(combiner, change, rules, target)
        return RetestLook.of(found, rules.primary, self.timed.suite_seconds(mark),
                             combiner.last_notes)  # fmt: skip

    def retest_set(self, look: str, changes: Sequence[KeptChange]) -> RetestLook:
        """The combine node's re-test of a set (``combine_kept``'s first step,
        ``combine_node._retest``: the greedy merge in the given order, the
        ABAB re-test, the suite on the tip); ``retest_one`` is its one-change
        case."""
        target, rules, combiner = self._rules(look)
        mark = len(self.timed.spans)
        found = _retest(combiner, changes, rules, target)
        return RetestLook.of(found, rules.primary, self.timed.suite_seconds(mark),
                             combiner.last_notes)  # fmt: skip

    def check_guards(self, run: LiveRun) -> None:
        """No request, the replay's phases only, every launch sandboxed and
        isolated, the user's repository unchanged; each message names its guard."""
        mode = (self.isolation.mode, self.isolation.missing)
        assert mode == ("required", None), f"isolation not required: {mode}"
        sent = (len(run.capture.messages()), len(run.records))
        assert sent == (0, 0), f"no request may be sent: {sent}"
        assert run.spent_usd <= run.cap_usd, f"spend over the cap: {run.spent_usd}"
        phases = self.launches.phases()
        assert phases, "no launch was recorded"
        allowed = PREFLIGHT_PHASE in phases and phases <= REPLAY_PHASES
        assert allowed, f"phases outside the replay: {sorted(phases)}"
        for launch in self.launches.launches:
            modes = (launch.network, launch.fs)
            assert modes == ("required", "required"), f"unsandboxed launch: {launch}"
            isolated = launch.net_isolated and launch.fs_isolated
            assert isolated, f"launch not isolated: {launch}"
        assert self.user.snapshot() == self._before, "user repository changed"
        worktrees = self.user.worktrees()
        assert len(worktrees) == 1, f"worktrees left: {worktrees}"


def check_settings(base: Settings = settings) -> None:
    """Refuse, before any clone, a process off the X2 measurement settings."""
    wrong = sorted(k for k, v in REPLAY_SETTINGS.items() if getattr(base, k) != v)
    if wrong:
        raise ValueError(f"{', '.join(wrong)} not as the X2 arms measured "
                         "(ci.yml's step3 rule, OP_COUNT_JUDGE=true, every other "
                         "measurement setting at its default)")  # fmt: skip
