"""The upstream corpus's verification (V9c): does the maintainer's fix pay?

A candidate counts only if its sealed key (``upstream.UpstreamCase.key``)
measurably speeds up the blind benchmark on a CI runner with the project's
own tests green and the output unchanged. No Claude request is sent, so the
cap is 0 USD (``VERIFY_RUN_CAP_USD``). Per candidate (``verify_case``):

- the user's repository exactly as the live suite builds it
  (``upstream.prepare_repo``), its licence file checked, then the key
  committed beside it (``commit_key``: ``git apply --cached`` on a scratch
  index, a commit whose parent is the base, under ``KEY_REF``; the checkout,
  the index and ``HEAD`` never move);
- the engine's own measurement path: ``GitPreflight`` in the ``required``
  sandbox, then the Step 3 noise rule's calibration (``calibrate``: A/A
  blocks, the floor ``max(2 %, 2 x the largest gap)``), then
  ``KEY_BLOCKS`` blocks of the base against the key, ABBA through
  ``measure_abab`` (``KeyRunner.compare``), and the test command once on
  each side (the key side must pass at least as many tests);
- ``summarize``: the gain of the pooled wall-time means, its threshold
  ``upstream.threshold(floor)`` (``max(2 x floor, 10 %)``) and the margin
  over it, the passing counts, and whether every run printed one output.
  Verified: the gain clears the threshold, both suites pass, the output is
  equal and the licence text is there;
- the guards (``check_verify_guards``): no request on the wire, only the
  verification phases, every launch sandboxed and isolated, the user's
  repository as it was after the key commit, one worktree.

A key that does not apply, a preflight refusal or a run that fails is a
``stopped`` row (recorded, not raised); a preparation that fails (an
interpreter outside the candidate's ``requires_python`` included) or a
guard breach is an ``error`` row, then raised. Results: one JSON line per
candidate to ``$LIVE_RESULTS_PATH``, the table to the job summary, a note
per candidate in the cost table; each row and the table name the
candidate's pool (``upstream.pool``: who set the key, what the before-tree
hints). The Lead copies each verified row (the CI run id, ``gain``,
``floor`` as ``noise_floor``, ``threshold``, ``workload_sha256``) into the
manifest's ``verified`` record (``upstream.Verified``): only such a
candidate reaches the live suite, and only with that workload.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import statistics
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from e2e.conftest import Isolation, LaunchLog, RepoSnapshot, UserRepo

from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.errors import EngineError
from autonomous_ai_agents.common.models import (
    METRIC_TESTS_PASSED,
    METRIC_WALL_TIME_S,
    Measurement,
    NoiseCalibration,
    Workload,
)
from autonomous_ai_agents.execution.git import GitWorkspace, repo_fingerprint
from autonomous_ai_agents.execution.measure import (
    AbabMeasured,
    Measured,
    measure_abab,
    run_tests,
)
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
from autonomous_ai_agents.orchestrator.nodes import _check_preflight

from .conftest import LiveRun
from .discovery_io import ResultsSink, cells, flag, write_markdown
from .noise import noise_guardrails
from .oss import PRODUCTION, CloneRefusedError, GitPolicy, _Git, _scratch_git
from .upstream import (
    UpstreamCase,
    licence_problem,
    pool,
    prepare_repo,
)
from .upstream import (
    threshold as threshold,
)

VERIFY_EXPERIMENT: Final = "upstream-verify"
VERIFY_RUN_CAP_USD: Final = 0.0  # no Claude request
VERIFY_JOB_MINUTES: Final = 150
"""Ten candidates a dispatch at about 6-12 minutes each (clone, preflight,
3 calibration and 3 key blocks of 12 launches, two suites), with room."""
CALIBRATION_BLOCKS: Final = 3  # the Step 3 rule's NOISE_CALIBRATION_BLOCKS
KEY_BLOCKS: Final = 3
KEY_PHASES: Final = ("upstream-base", "upstream-fixed")
VERIFY_PHASES: Final = frozenset({"preflight", *CALIBRATE_PHASES, *KEY_PHASES})
KEY_REF: Final = "refs/upstream/key"
_KEY_OWNER: Final = "the key comparison"


LICENCE_MAX_BYTES: Final = 256 * 1024


def licence_text(path: Path) -> str:
    """The checkout's licence file: a regular file read without following a
    link, at most ``LICENCE_MAX_BYTES``; anything else reads as empty."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return ""
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return ""
        return os.read(fd, LICENCE_MAX_BYTES).decode("utf-8", "replace")
    finally:
        os.close(fd)


def verify_need() -> float:
    """What a verification dispatch asks the ledger for: nothing."""
    return VERIFY_RUN_CAP_USD


def commit_key(
    user: UserRepo,
    case: UpstreamCase,
    *,
    policy: GitPolicy = PRODUCTION,
    environ: Mapping[str, str] | None = None,
) -> str:
    """The sealed key applied to ``user.base`` as a new commit under
    ``KEY_REF``, through a scratch index: nothing checked out moves."""
    data = case.key_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != case.key.sha256:
        raise CloneRefusedError(f"{case.id}: the key's sha256 is not the sealed one")
    scratch = Path(tempfile.mkdtemp(prefix="upstream-key-"))
    try:
        with _scratch_git(user.path, policy, environ) as git:
            env = {**git.env, "GIT_INDEX_FILE": str(scratch / "index")}
            staged = _Git(user.path, env, policy)
            staged("read-tree", user.base)
            try:
                staged("apply", "--cached", "--", str(case.key_path))
            except CloneRefusedError as exc:
                raise CloneRefusedError(f"the key does not apply: {exc}") from None
            tree = staged("write-tree")
            key = git("commit-tree", tree, "-p", user.base, "-m", f"key: {case.id}")
            git("update-ref", KEY_REF, key)
            return key
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


class KeyRunner(GitBaselineRunner):
    """The real baseline runner plus ``compare``: the base and the key in two
    fresh worktrees, every workload ABBA through ``measure_abab`` for
    ``blocks`` blocks, then the suite once on each side."""

    def compare(
        self,
        workloads: Sequence[Workload],
        *,
        run_id: str,
        base: str,
        fixed: str,
        blocks: int,
    ) -> tuple[tuple[AbabMeasured, ...], Measured, Measured]:
        require_dir_name("run id", run_id)
        sides = [phase_dirs(run_id, name) for name in KEY_PHASES]
        before = repo_fingerprint(self._git)
        found: list[AbabMeasured] = []
        suites: list[Measured] = []
        failed: RunFailure | None = None
        with owned_phases(self._git, _KEY_OWNER, *sides):
            a, b = (
                self._make_phase(self._git.add_worktree(d.worktree, commit), d)
                for d, commit in zip(sides, (base, fixed), strict=True)
            )
            try:
                for _ in range(blocks):
                    for workload in workloads:
                        found.append(measure_abab(a, b, workload))
                        self._note("key", found[-1].notes)
                suites.append(run_tests(a, self._project, workloads))
                count = suites[0].tests_counted
                suites.append(
                    run_tests(b, self._project, workloads, baseline_count=count)
                )
            except RunFailure as failure:
                self._note("key", failure.notes)
                failed = failure
            self._tampered(before, what=_KEY_OWNER)
        if failed is not None:
            raise EngineError(
                f"the key comparison could not be measured: {failed.reason}"
            )
        return tuple(found), suites[0], suites[1]


# ---------------------------------------------------------------------------
# The gain, its threshold and the verdict
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KeyResult:
    """One candidate measured (or stopped), and why it is or is not verified."""

    id: str
    lib: str
    risk: str
    floor: float | None
    threshold: float | None
    gain: float | None
    block_gains: tuple[float, ...]
    tests_base: int | None  # passing tests; None: the suite failed
    tests_fixed: int | None
    output_equal: bool
    stopped: str | None
    wall_s: float
    licence: str | None = None  # a licence problem
    pool: str = "-"  # upstream.pool: who set the key, what the tree hints
    workload_sha256: str = ""  # the benchmark measured (Verified binds it)

    @classmethod
    def stopped_at(cls, case: UpstreamCase, reason: str, wall_s: float) -> KeyResult:
        return cls(
            case.id, case.lib, case.contamination_risk, None, None, None, (),
            None, None, False, reason, wall_s, None, pool(case),
            case.workload_sha256,
        )  # fmt: skip

    @property
    def margin(self) -> float | None:
        if self.gain is None or self.threshold is None:
            return None
        return self.gain - self.threshold

    def why_not(self) -> str:
        """Empty when verified; else every condition the candidate missed."""
        if self.stopped is not None:
            return f"stopped: {self.stopped}"
        reasons = []
        margin = self.margin
        if margin is None or margin <= 0:
            gain, least = self.gain or 0.0, self.threshold or 0.0
            reasons.append(f"gain {gain:.1%} does not clear {least:.1%}")
        if self.tests_base is None:
            reasons.append("tests fail at the before-commit")
        if self.tests_fixed is None:
            reasons.append("tests fail with the key")
        if not self.output_equal:
            reasons.append("output differs or has no fingerprint")
        if self.licence is not None:
            reasons.append(self.licence)
        return "; ".join(reasons)

    @property
    def verified(self) -> bool:
        return not self.why_not()

    def row(self) -> dict[str, object]:
        return {
            "experiment": VERIFY_EXPERIMENT, "kind": "candidate", "id": self.id,
            "lib": self.lib, "risk": self.risk, "floor": self.floor,
            "threshold": self.threshold, "gain": self.gain, "margin": self.margin,
            "block_gains": list(self.block_gains), "tests_base": self.tests_base,
            "tests_fixed": self.tests_fixed, "output_equal": self.output_equal,
            "verified": self.verified, "why_not": self.why_not(),
            "stopped": self.stopped, "licence": self.licence, "wall_s": self.wall_s,
            "pool": self.pool, "workload_sha256": self.workload_sha256,
        }  # fmt: skip


def _wall(rows: Sequence[Measurement]) -> list[Measurement]:
    return [m for m in rows if m.metric == METRIC_WALL_TIME_S]


def _gain(a: Sequence[float], b: Sequence[float]) -> float:
    base = statistics.fmean(a)
    return (base - statistics.fmean(b)) / base if base > 0 else 0.0


def _passed(suite: Measured) -> int | None:
    rows = [m for m in suite.measurements if m.metric == METRIC_TESTS_PASSED]
    if not rows or any(m.stats.mean != 1.0 for m in rows):
        return None
    return suite.tests_counted or 0


def summarize(
    case: UpstreamCase,
    calibration: NoiseCalibration,
    blocks: Sequence[AbabMeasured],
    tests_base: Measured,
    tests_fixed: Measured,
    wall_s: float,
    licence: str | None = None,
) -> KeyResult:
    """The gain of the pooled wall-time means of B against A, each block's,
    the threshold over the calibrated floor, the suites and the output."""
    a = [s for block in blocks for m in _wall(block.a) for s in m.samples]
    b = [s for block in blocks for m in _wall(block.b) for s in m.samples]
    gains = tuple(
        _gain([s for m in _wall(x.a) for s in m.samples], [s for m in _wall(x.b) for s in m.samples])
        for x in blocks
    )  # fmt: skip
    prints = {m.output_fingerprint for x in blocks for m in (*_wall(x.a), *_wall(x.b))}
    return KeyResult(
        case.id, case.lib, case.contamination_risk, calibration.floor,
        threshold(calibration.floor), _gain(a, b) if a and b else None, gains,
        _passed(tests_base), _passed(tests_fixed),
        len(prints) == 1 and None not in prints, None, wall_s, licence,
        pool(case), case.workload_sha256,
    )  # fmt: skip


# ---------------------------------------------------------------------------
# The recorder and the guards
# ---------------------------------------------------------------------------


def _f(value: float | None) -> str:
    return "-" if value is None else f"{value:.4f}"


def note(result: KeyResult) -> str:
    if result.verified and result.gain is not None and result.margin is not None:
        return (
            f"UPSTREAM {result.id}: verified, gain {result.gain:.1%} against"
            f" {result.threshold:.1%} (margin {result.margin:+.1%})"
        )
    return f"UPSTREAM {result.id}: not verified ({result.why_not()})"


class VerifyRecorder:
    """Rows to the sink, notes to each run, the table at the end."""

    def __init__(self, sink: ResultsSink) -> None:
        self.sink = sink
        self.results: list[KeyResult] = []
        self.errors: list[tuple[str, str]] = []

    def record(self, result: KeyResult, run: LiveRun) -> None:
        self.results.append(result)
        self.sink.write(result.row())
        run.note(note(result))

    def record_error(
        self,
        name: str,
        run: LiveRun,
        error: str,
        measured: Mapping[str, object] | None = None,
    ) -> None:
        self.errors.append((name, error))
        row: dict[str, object] = {
            "experiment": VERIFY_EXPERIMENT, "kind": "error", "id": name,
            "error": error,
        }  # fmt: skip
        if measured is not None:
            row["measured"] = dict(measured)
        self.sink.write(row)
        run.note(f"UPSTREAM {name}: error {error}")

    def markdown(self) -> str:
        lines = [
            "## Upstream corpus verification (maintainer fix against the before-commit)",
            "",
            "| id | lib | risk | floor | threshold | gain | margin | tests before "
            "| tests with key | output equal | verified | why not | pool |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- "
            "| --- | --- | --- |",
        ]
        for r in self.results:
            lines.append(cells([
                r.id, r.lib, r.risk, _f(r.floor), _f(r.threshold), _f(r.gain),
                _f(r.margin), "fail" if r.tests_base is None else r.tests_base,
                "fail" if r.tests_fixed is None else r.tests_fixed,
                flag(r.output_equal), flag(r.verified), r.why_not() or "-", r.pool,
            ]))  # fmt: skip
        for name, error in self.errors:
            lines.append(cells([name, "error", error, *("-",) * 10]))
        verified = sum(r.verified for r in self.results)
        tail = f"{verified} of {len(self.results)} verified"
        if self.errors:
            tail += f", {len(self.errors)} errors"
        return "\n".join([*lines, "", tail])

    def finish(self, echo: Callable[[str], None]) -> None:
        write_markdown("Upstream verify", self.markdown(), self.sink.environ, echo)


def check_verify_guards(
    run: LiveRun,
    user: UserRepo,
    before: RepoSnapshot,
    launches: LaunchLog,
    isolation: Isolation,
) -> None:
    """No request, the verification phases only, every launch sandboxed and
    isolated, the user's repository unchanged. Each message names its guard."""
    mode = (isolation.mode, isolation.missing)
    assert mode == ("required", None), f"isolation not required: {mode}"
    sent = (len(run.capture.messages()), len(run.records))
    assert sent == (0, 0), f"no request may be sent: {sent}"
    assert run.spent_usd <= run.cap_usd, f"spend over the cap: {run.spent_usd}"
    phases = launches.phases()
    assert phases, "no launch was recorded"
    allowed = "preflight" in phases and phases <= VERIFY_PHASES
    assert allowed, f"phases outside the verification: {sorted(phases)}"
    for launch in launches.launches:
        modes = (launch.network, launch.fs)
        assert modes == ("required", "required"), f"unsandboxed launch: {launch}"
        isolated = launch.net_isolated and launch.fs_isolated
        assert isolated, f"launch not isolated: {launch}"
    assert user.snapshot() == before, "user repository changed"
    worktrees = user.worktrees()
    assert len(worktrees) == 1, f"worktrees left: {worktrees}"


# ---------------------------------------------------------------------------
# The driver
# ---------------------------------------------------------------------------


def _measure(
    case: UpstreamCase,
    user: UserRepo,
    key: str,
    isolation: Isolation,
    launches: LaunchLog,
    blocks: tuple[int, int],
) -> tuple[NoiseCalibration, tuple[AbabMeasured, ...], Measured, Measured]:
    """Preflight, calibration and the key comparison (``EngineError``: stop)."""
    project = case.project(user.path)
    workload = case.workload(project)
    mode = isolation.mode
    preflight = GitPreflight(network=mode, fs=mode, run=launches)
    report = preflight.check(project, [workload], noise_guardrails(project.id))
    _check_preflight(report, [workload])
    resolved = project.model_copy(update={"test_command": report.test_command})
    git = GitWorkspace(
        user.path, executable=settings.GIT_EXECUTABLE, timeout_s=settings.GIT_TIMEOUT_S
    )
    runner = KeyRunner(resolved, git=git, network=mode, fs=mode, run=launches)
    loads = tuple(report.workloads)
    calibration = runner.calibrate(
        loads, run_id="upstream-calibrate", commit=user.base, blocks=blocks[0]
    )
    found = runner.compare(
        loads, run_id="upstream-key", base=user.base, fixed=key, blocks=blocks[1]
    )
    return (calibration, *found)


def verify_case(
    case: UpstreamCase,
    run: LiveRun,
    root: Path,
    isolation: Isolation,
    recorder: VerifyRecorder,
    *,
    policy: GitPolicy = PRODUCTION,
    environ: Mapping[str, str] | None = None,
    calibration_blocks: int = CALIBRATION_BLOCKS,
    key_blocks: int = KEY_BLOCKS,
) -> KeyResult:
    """One candidate prepared, keyed, measured, guarded and recorded."""
    started = time.monotonic()
    launches = LaunchLog()
    try:
        user = prepare_repo(case, root / "user", policy=policy, environ=environ)
        licence = licence_problem(case, licence_text(user.path / case.license_file))
        try:
            key = commit_key(user, case, policy=policy, environ=environ)
        except CloneRefusedError as exc:
            result = KeyResult.stopped_at(case, str(exc), time.monotonic() - started)
            recorder.record(result, run)
            return result
        before = user.snapshot()
        try:
            found = _measure(case, user, key, isolation, launches, (calibration_blocks, key_blocks))  # fmt: skip
            wall = time.monotonic() - started
            result = summarize(case, *found, wall, licence)
        except EngineError as exc:
            result = KeyResult.stopped_at(case, str(exc), time.monotonic() - started)
    except BaseException as exc:
        recorder.record_error(case.id, run, f"{type(exc).__name__}: {exc}")
        raise
    try:
        check_verify_guards(run, user, before, launches, isolation)
    except BaseException as exc:
        recorder.record_error(case.id, run, f"guards: {exc}", result.row())
        raise
    recorder.record(result, run)
    return result
