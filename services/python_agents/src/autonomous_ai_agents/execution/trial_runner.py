"""The real runners: one trial (``GitTrialRunner``) and the baseline (``GitBaselineRunner``).

Both own their phase (decision 38): ``<WORKTREE_ROOT>/<run>/<phase>`` at the
pinned commit plus ``<run>/_scratch/<phase>`` and ``<run>/_probe/<phase>``
(``measure.make_phase``: sandbox, environment, the reset before every run),
fingerprinted before and after (``repo_fingerprint``, decision 16), and
removed again by the shared ``phase.owned_phases`` cleanup (a dir it cannot
remove safely is an ``EngineError`` after every step ran, unless an error is
already on its way).

A trial (spec section 4, steps 1 to 8) is ``trial-<hypothesis id>``: the
editor edits the worktree; the change is captured (``--no-renames``, strict
UTF-8, a ``GitError`` fails the trial); ``check_capture`` and
``check_diff_all`` run, and with a quality check ``check_quality_references``
(D37's tripwire); any violation fails it and it is **never executed**.
Otherwise it is committed with the engine identity, the base dates and an
``Engine-Trial: <id>`` trailer, ``clean -ffdx``-ed and put on its own ref
``refs/heads/<prefix>trial-<run>-<hyp>`` (decision 18: the id is
``uuid5(branch@round)``; an existing ref moves only when its commit carries
this trial's trailer, else ``EngineError``; a re-run that commits nothing
drops it), then measured with the baseline's test count. F1 excludes only the
own ref, which must then be absent or at ``Trial.commit``
(``RepoTamperedError``). The editor, cost and the run notes: see
``GitTrialRunner``.

An editor the cost cap stopped before anything was written or spent raises
``TrialUnaffordable``: the trial never started, so it is no rejected change.
Any exception that ends a trial carries the money it spent (``add_spend``),
and the own ref it moved is put back (nothing records that trial any more),
unless a worktree checked it out meanwhile: that ref stays, with a note.

Fix retry (D12-D15): when the trial's own workload crashes with a fixable
Python error (``retry.classify``), the runner allows ``fix_retries`` and the
brief's ``fix_retries_left`` both have one left and the trial's budget holds at
least ``retry_floor_usd``, the worktree is reset to the first commit and the
editor gets one fresh request whose only run output is the closed feedback's
``render()``. The writes of both attempts merge (under the write limits),
capture and every anti-cheat rule run again on the diff against the base, and
the second commit's parent is the base, so the trial stays one child of it.
Anything else keeps the first failure and its commit, with a ``retry_notes``
line (the notes, never the prompt, name what was withheld).

Re-edit (N0b, D62): a first edit whose only refusals are ``unparsable_source``
(a file the engine cannot parse, so nothing was scanned or run) spends the
same fix retry under the same caps: the editor gets one fresh request whose
feedback is those violations' engine messages (the file, the line and the
parser's message). No reset: nothing ran and nothing was committed, so the
worktree is the first edit as written. The re-edit is captured and checked
again against the base before anything runs. The feedback is a function of
the captured blobs only, which hold the editor's writes and tracked base text
it may read (a path the editor may not read gets no re-edit), so it carries
nothing from the user's machine and adds nothing to D13's residual. A re-edit
that does not hold keeps the refusal, its own ref put back.

Paired trials (D41 a, ``paired``): every attempt, a retry's too, is measured
ABBA (``measure_abab``) against a fresh twin worktree at the base,
``twin-trial-<hyp>`` (a prefix no trial phase has); the twin's rows are
``Trial.base_measurements`` and the suite runs once, on the trial. A crash on
the twin is an ``EngineError`` (the base, not the hypothesis, failed, as at
baseline): never retried, no verdict, the spend on the error.
The noise calibration (D41 c, ``GitBaselineRunner.calibrate``) measures the
base against a second base worktree in A/A blocks.

Quality (D37, ``scorer``; without one every runner is Step 2's): every phase
any runner builds deletes the check's frozen files before each workload
launch (``make_phase(mask=)``; the suite is unmasked), and each measured side
gets one ``quality:<name>`` row (``n=1``, unit ``score``) scored from its
agreed output bytes, cached by ``raw_fingerprint``; an unscoreable output
gets no row, so completeness rejects it (``missing_measurement``), with a
note that names counts, never the bytes. The baseline freezes the files
(``quality_files``), scores twice and notes a tracked input a workload names
that carries the labels column (``label_leaks``; the check is sound only
without one). A trial freezes against ``Baseline.quality_files`` once per run
(a resume), and its editor's brief always protects and read-denies the files.
"""

from __future__ import annotations

import contextlib
import functools
import glob
import math
import os
import posixpath
import secrets
import sys
import uuid
from collections.abc import Callable, Collection, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, replace
from pathlib import Path, PurePath
from typing import Protocol

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.common.config import (
    FIX_RETRIES_MAX,
    IsolationMode,
    settings,
)
from autonomous_ai_agents.common.errors import (
    EngineError,
    RepoTamperedError,
    TrialUnaffordable,
    add_spend,
)
from autonomous_ai_agents.common.models import (
    METRIC_WALL_TIME_S,
    NOISE_CALIBRATION_BLOCKS_MAX,
    NOISE_FLOOR_MIN,
    Baseline,
    FrozenFile,
    Hypothesis,
    Measurement,
    NoiseCalibration,
    Project,
    QualityCheck,
    RunStats,
    Trial,
    TrialStatus,
    Violation,
    ViolationRule,
    Workload,
    utc_now,
)
from autonomous_ai_agents.common.paths import (
    READ_DENY_PATTERNS,
    RESERVED_MODULES,
    matches_pattern,
    normalize_path,
)
from autonomous_ai_agents.common.refnames import branch_prefix_problem
from autonomous_ai_agents.execution.crash import parse_traceback
from autonomous_ai_agents.execution.editor import STOP_BUDGET
from autonomous_ai_agents.execution.editor_tools import EditorLimits
from autonomous_ai_agents.execution.git import (
    _DIFF,
    _PATCH,
    GitError,
    GitWorkspace,
    _require_oid,
    _require_path,
    repo_fingerprint,
)
from autonomous_ai_agents.execution.measure import (
    Phase,
    RunOnce,
    baseline_test_count,
    make_phase,
    measure_abab,
    measure_workload,
    python_module,
    run_tests,
)
from autonomous_ai_agents.execution.phase import (
    PhaseDirs,
    owned_phases,
    phase_dirs,
    require_dir_name,
)
from autonomous_ai_agents.execution.procrun import (
    OutputCaps,
    RunFailure,
    RunSample,
    run_once,
)
from autonomous_ai_agents.execution.protocols import (
    Change,
    CodeEditor,
    EditResult,
    EditTask,
    TrialBrief,
    WorktreeHandle,
)
from autonomous_ai_agents.execution.quality import (
    QualityGit,
    QualityScorer,
    UnscoreableError,
    label_column_leaks,
)
from autonomous_ai_agents.execution.retry import ClosureIndex, TrialFeedback, classify
from autonomous_ai_agents.execution.sandbox import SandboxPolicy
from autonomous_ai_agents.optimization.anticheat import (
    DEFAULT_MODULE_ROOTS,
    check_capture,
    check_diff_all,
    check_quality_references,
    is_utf8,
)

TRIAL_NAMESPACE = uuid.UUID("3f0c6a52-7d1e-5b9a-8c4f-2e6d9b1a7c30")
"""uuid5 namespace of trial ids: ``uuid5(TRIAL_NAMESPACE, "<branch>@<round>")``."""
TRAILER = "Engine-Trial"
BASELINE_PHASE = "baseline"
CALIBRATE_PHASES = ("calibrate", "twin-calibrate")
CALIBRATION = "the noise calibration"
"""The noise calibration's two base worktrees (A and A')."""
TWIN_FAILED = "the paired base run failed"
"""The ``EngineError`` of a paired trial whose twin, not the trial, failed."""
_TIME_METRICS = (METRIC_WALL_TIME_S,)
"""Calibrated metrics: the engine's time objective. CPU time's tick
granularity would inflate the floor every judge must clear."""
NONDETERMINISTIC_NOTE = "did not agree on one output"
"""In a note, the measurement's nondeterministic-output warning."""
INVOKE_PROTECTED: tuple[str, ...] = (
    "**/tasks.py",
    "**/tasks/**",
    "**/invoke.yaml",
    "**/invoke.yml",
    "**/invoke.json",
    "**/invoke.py",
)
"""What invoke reads from the working dir up (its tasks and its project config):
protected when a workload or the test command runs invoke."""
_INVOKE = frozenset({"invoke", "inv"})
_EDIT_DONE = "end_turn"
_REGULAR = frozenset({"100644", "100755"})
_SUBJECT_CHARS = 72
_KEPT = "first failure kept"
_UNPARSABLE = ViolationRule.unparsable_source.value
_TYPE_CHARS = 64
_NO_CLOSURE = ClosureIndex(frozenset(), {}, complete=False)
"""Classifies fixability without reading any source (type only, nothing sent)."""


@dataclass
class _Progress:
    """What one trial did so far, for when it raises: the editor's budget, the
    charged trial once the edit ended, and the commit its own ref moved to."""

    budget: Budget
    trial: Trial | None = None
    moved: str | None = None

    def spent(self, cap: float) -> tuple[float, int]:
        """The money spent, never above the trial's budget ``cap``."""
        usd, tokens = self.budget.spent_usd, self.budget.tokens
        if self.trial is not None:
            usd, tokens = (
                max(usd, self.trial.cost_usd),
                max(tokens, self.trial.tokens_used),
            )
        return min(usd, cap), tokens


@dataclass(frozen=True)
class _Job:
    """One trial's fixed inputs, shared by its attempts."""

    handle: WorktreeHandle
    dirs: PhaseDirs
    hypothesis: Hypothesis
    workloads: tuple[Workload, ...]
    baseline: Baseline
    base: str
    tracked: tuple[str, ...]
    scope: RunScope
    brief: TrialBrief
    prior: str | None
    own_ref: str
    twin: PhaseDirs
    patterns: tuple[str, ...]
    """``brief.protected`` as the diff check matches it: frozen paths escaped."""


@dataclass
class _Side:
    """Whether the latest launch of a paired measurement was the twin's."""

    twin: bool = False


def _marked(phase: Phase, side: _Side, twin: bool) -> Phase:
    """``phase`` recording in ``side`` that its reset (every launch's first
    step) ran, so a ``RunFailure`` names the side it came from."""

    def reset() -> None:
        side.twin = twin
        phase.reset()

    return replace(phase, reset=reset)


def _twin_dirs(dirs: PhaseDirs) -> PhaseDirs:
    return phase_dirs(dirs.run.name, f"twin-{dirs.worktree.name}")


@dataclass(frozen=True)
class _Tried:
    """One attempt's trial, the editor's record so far and its crash, if any."""

    trial: Trial
    result: EditResult
    crash: RunFailure | None = None


class EditorFactory(Protocol):
    """Builds the run's editor; ``functools.partial(ClaudeEditor, transport)`` fits."""

    def __call__(
        self, *, module_roots: AbstractSet[str], reserved_modules: AbstractSet[str]
    ) -> CodeEditor: ...


@dataclass(frozen=True)
class RunScope:
    """What a run's editor and ``check_capture`` guard, and its extra patterns."""

    module_roots: frozenset[str]
    reserved_modules: frozenset[str]
    protected: tuple[str, ...]


def trial_id_for(branch: str, round: int) -> str:
    """The trial's deterministic id, so a re-executed node rebuilds the same one."""
    return str(uuid.uuid5(TRIAL_NAMESPACE, f"{branch}@{round}"))


def _root(directory: str) -> str:
    clean = normalize_path(directory)
    return "" if clean == "." else clean


def run_scope(
    project: Project,
    workloads: Sequence[Workload],
    tracked: Collection[str],
    *,
    worktree: Path | None = None,
) -> RunScope:
    """Module roots: the repo root, ``src``, every working dir and the dir of every
    tracked file a command names (``argv[0]`` from the root, the rest from its
    working dir), plus, for one that is a link in the base ``worktree``, the dir
    of its resolved target inside it (CPython puts that one on ``sys.path``);
    reserved: ``RESERVED_MODULES`` plus every ``-m`` target's top-level name;
    ``INVOKE_PROTECTED`` when a command runs invoke."""
    roots, reserved = set(DEFAULT_MODULE_ROOTS), set(RESERVED_MODULES)
    commands = [(w.command, w.working_dir) for w in workloads]
    if project.test_command is not None:
        commands.append((project.test_command, "."))
    invoke = False
    for argv, workdir in commands:
        roots.add(_root(workdir))
        found = python_module(argv)
        module = None if found is None else found[0].split(".", 1)[0]
        if module is not None:  # its top-level name, as module_shadow reads it
            reserved.add(module)
        invoke |= PurePath(argv[0]).name in _INVOKE or module == "invoke"
        for index, arg in enumerate(argv):
            if arg.startswith("-") or os.path.isabs(arg):
                continue
            joined = arg if index == 0 else posixpath.join(workdir, arg)
            with contextlib.suppress(ValueError):  # outside the repo: no root
                rel = normalize_path(posixpath.normpath(joined))
                if rel in tracked:
                    roots.add(_root(posixpath.dirname(rel)))
                    target = None if worktree is None else _link_target(worktree, rel)
                    if target is not None:
                        roots.add(_root(posixpath.dirname(target)))
    extra = INVOKE_PROTECTED if invoke else ()
    return RunScope(frozenset(roots), frozenset(reserved), extra)


def _link_target(worktree: Path, rel: str) -> str | None:
    """The repo path a tracked link ``rel`` resolves to; None for a file or a
    link out of the worktree."""
    if not os.path.islink(worktree / rel):
        return None
    base, real = os.path.realpath(worktree), os.path.realpath(worktree / rel)
    if os.path.commonpath((base, real)) != base:
        return None
    return Path(real).relative_to(base).as_posix()


def _base_dirs(tracked: Collection[str]) -> frozenset[str]:
    """The base tree's directories (as ``ls-tree -d -r``), names normalize keeps."""
    found: set[str] = set()
    for path in tracked:
        parts = path.split("/")
        for depth in range(1, len(parts)):
            directory = "/".join(parts[:depth])
            with contextlib.suppress(ValueError):
                if normalize_path(directory) == directory:
                    found.add(directory)
    return frozenset(found)


class RunnerScorer(QualityScorer, Protocol):
    """``quality.FrozenScorer`` as the runners use it: its check names the
    row's metric and the mask."""

    @property
    def check(self) -> QualityCheck: ...


class NoteTap:
    """A ``RunOnce`` keeping each distinct note of its runs: given to the
    scorer and to the baseline runner, which reports the scorer's isolation
    notes once (U19 review N4)."""

    def __init__(self, run: RunOnce = run_once) -> None:
        self._run, self._notes = run, dict[str, None]()

    def __call__(
        self, argv: Sequence[str], cwd: Path, env: Mapping[str, str],
        sandbox: SandboxPolicy, timeout_s: float, caps: OutputCaps, *,
        fresh_dirs: Sequence[Path] = (),
    ) -> RunSample:  # fmt: skip
        sample = self._run(argv, cwd, env, sandbox, timeout_s, caps, fresh_dirs=fresh_dirs)  # fmt: skip
        self._notes.update(dict.fromkeys(sample.notes))
        return sample

    def drain(self) -> tuple[str, ...]:
        notes, self._notes = tuple(self._notes), {}
        return notes


class QualityHooks:
    """One runner's use of the shared scorer (D37): the mask, one freeze per
    (run, commit), the rows. Without a scorer: no mask, freeze or row."""

    def __init__(self, scorer: RunnerScorer | None) -> None:
        self.scorer = scorer
        self.mask = () if scorer is None else scorer.check.frozen_paths
        self.files: tuple[FrozenFile, ...] = ()
        self._key: tuple[str, str] | None = None

    def freeze(
        self, git: QualityGit, run_id: str, commit: str, *,
        recorded: Sequence[FrozenFile] = (),
    ) -> None:  # fmt: skip
        if self.scorer is not None and self._key != (run_id, commit):
            self.files = self.scorer.freeze(git, commit, run_id=run_id, recorded=recorded)  # fmt: skip
            self._key = (run_id, commit)

    def rows(
        self, workload: Workload, measured: Sequence[Measurement], output: bytes | None,
        *, trial_id: str | None, notes: list[str], baseline: bool = False,
    ) -> tuple[Measurement, ...]:  # fmt: skip
        """``workload``'s quality row: ``output`` (the agreed bytes) scored once,
        keyed by the exact ``raw_fingerprint`` of its ``measured`` rows (``None``,
        agreed only within a tolerance: scored uncached); unscoreable: none."""
        if self.scorer is None:
            return ()
        raw = next((m.raw_fingerprint for m in measured), None)
        score = self.scorer.score_baseline if baseline else self.scorer.score
        try:
            value = score(output, raw)
        except UnscoreableError as error:  # its message never quotes the output
            name = self.scorer.check.name
            notes.append(f"workload {workload.name!r}: quality check {name!r}: {error}; no quality row")  # fmt: skip
            return ()
        stats = RunStats.from_samples((value,), unit="score")
        metric = self.scorer.check.metric
        return (Measurement(workload_id=workload.id, trial_id=trial_id, metric=metric, stats=stats, samples=(value,)),)  # fmt: skip


def _label_leaks(
    git: GitWorkspace, commit: str, check: QualityCheck, workloads: Sequence[Workload]
) -> tuple[str, ...]:
    """D37's precondition: each column of a tracked regular file a workload's
    argv names (``argv[0]`` from the root, the rest from its working dir; not
    a frozen file) holding the labels. Each is read once, at most the cap and
    one byte; one past the cap is not scanned."""
    if check.labels is None:
        return ()
    cap, modes = settings.QUALITY_MAX_FROZEN_BYTES, git.blob_modes(commit)
    files: dict[str, bytes] = {}
    seen = set(check.frozen_paths)
    for workload in workloads:
        for index, arg in enumerate(workload.command):
            if arg.startswith("-") or os.path.isabs(arg):
                continue
            joined = arg if index == 0 else posixpath.join(workload.working_dir, arg)
            try:
                rel = normalize_path(posixpath.normpath(joined))
            except ValueError:  # outside the repository
                continue
            if modes.get(rel) in _REGULAR and rel not in seen:
                seen.add(rel)
                data = git.read_blob(commit, rel, limit=cap + 1)
                if len(data) <= cap:
                    files[rel] = data
    labels = git.read_blob(commit, check.labels, limit=cap + 1)
    return label_column_leaks(labels, files)


class _PhaseOwner:
    """What both runners share: git, the phase factory, notes, the cleanup,
    the quality hooks."""

    _what = "the runner"

    def __init__(
        self,
        project: Project,
        *,
        git: GitWorkspace | None = None,
        network: IsolationMode | None = None,
        fs: IsolationMode | None = None,
        platform: str = sys.platform,
        base_env: Mapping[str, str] | None = None,
        run: RunOnce = run_once,
        on_note: Callable[[str], None] | None = None,
        scorer: RunnerScorer | None = None,
        scorer_notes: NoteTap | None = None,
    ) -> None:
        self._project = project
        self._quality, self._scorer_notes = QualityHooks(scorer), scorer_notes
        self._git = GitWorkspace(Path(project.root_path)) if git is None else git
        self._phase = functools.partial(
            make_phase, network=network, fs=fs, platform=platform, base_env=base_env
        )
        self._run = run
        self._on_note = on_note

    @property
    def git(self) -> GitWorkspace:
        return self._git

    def _note(self, prefix: str, notes: Sequence[str]) -> None:
        if self._on_note is not None:
            for note in notes:
                self._on_note(f"{prefix}: {note}")

    def _make_phase(self, handle: WorktreeHandle, dirs: PhaseDirs) -> Phase:
        """The phase of ``handle``, masking the quality check's frozen files
        before each workload launch (D37): every phase, so no side can differ."""
        return self._phase(
            self._git, handle, scratch=dirs.scratch, probe=dirs.probe, run=self._run,
            mask=self._quality.mask,
        )  # fmt: skip

    def _measure(
        self,
        phase: Phase,
        workloads: Sequence[Workload],
        *,
        prefix: str,
        trial_id: str | None,
        baseline_count: int | None,
        twin: Phase | None = None,
        baseline: bool = False,
    ) -> tuple[tuple[Measurement, ...], tuple[Measurement, ...]]:
        """``measure_workload`` per workload, or ABBA against ``twin`` (A), each
        side's quality row after its rows (``baseline``: scored twice), then
        the suite once on ``phase``: (the twin's rows, ``phase``'s rows); notes
        emitted. ``RunFailure`` propagates, its notes emitted."""
        base: list[Measurement] = []
        rows: list[Measurement] = []
        hooks = self._quality
        try:
            for workload in workloads:
                notes: list[str] = []
                if twin is None:
                    alone = measure_workload(phase, workload, trial_id=trial_id)
                    notes.extend(alone.notes)
                    own = (*alone.measurements, *hooks.rows(
                        workload, alone.measurements, alone.outputs,
                        trial_id=trial_id, notes=notes, baseline=baseline,
                    ))  # fmt: skip
                else:
                    paired = measure_abab(twin, phase, workload, trial_id_b=trial_id)
                    notes.extend(paired.notes)
                    a = hooks.rows(workload, paired.a, paired.outputs_a, trial_id=None, notes=notes)  # fmt: skip
                    b = hooks.rows(workload, paired.b, paired.outputs_b, trial_id=trial_id, notes=notes)  # fmt: skip
                    base.extend((*paired.a, *a))
                    own = (*paired.b, *b)
                self._note(prefix, notes)
                rows.extend(own)
            suite = run_tests(
                phase,
                self._project,
                workloads,
                baseline_count=baseline_count,
                trial_id=trial_id,
            )
        except RunFailure as failure:
            self._note(prefix, failure.notes)
            raise
        self._note(prefix, suite.notes)
        return tuple(base), (*rows, *suite.measurements)

    def _checked_out(self, ref: str) -> bool:
        return ref.casefold() in {
            b.casefold() for b in self._git.checked_out_branches()
        }

    def _refuse_checked_out(self, ref: str) -> None:
        """Moving a branch a worktree has checked out moves that HEAD too."""
        if self._checked_out(ref):
            raise EngineError(
                f"refusing to move {ref}: it is checked out in a worktree; check"
                " out another branch there, then run the trial again"
            )

    def _tampered(
        self,
        before: str,
        exclude: frozenset[str] = frozenset(),
        *,
        what: str | None = None,
    ) -> None:
        if repo_fingerprint(self._git, exclude_refs=exclude) != before:
            raise RepoTamperedError(
                f"the repository changed while {what or self._what} ran: its"
                " refs, config or hooks differ from before the run"
            )


class GitBaselineRunner(_PhaseOwner):
    """The real ``BaselineRunner``: every workload at ``commit``, then the suite
    once (its ``tests_passed`` rows record the passing count trials must reach).
    A ``RunFailure`` is an ``EngineError`` once F1 held. Notes go to
    ``on_note`` prefixed ``baseline:``; with a ``scorer`` (module docstring),
    ``scorer_notes``, the scorer's ``NoteTap``, adds its run notes once."""

    _what = "the baseline"
    _leaks: tuple[str, ...] = ()

    @property
    def quality_files(self) -> tuple[FrozenFile, ...]:
        """The frozen files the latest ``measure`` recorded (``Baseline.quality_files``)."""
        return self._quality.files

    @property
    def label_leaks(self) -> tuple[str, ...]:
        """``path column N`` of each tracked input carrying the labels (D37)."""
        return self._leaks

    def measure(
        self, workloads: Sequence[Workload], *, run_id: str, commit: str | None
    ) -> tuple[Measurement, ...]:
        if commit is None:
            raise ValueError("the baseline needs the pinned commit, got None")
        require_dir_name("run id", run_id)
        dirs = phase_dirs(run_id, BASELINE_PHASE)
        self._quality.freeze(self._git, run_id, commit)
        scorer = self._quality.scorer
        check = None if scorer is None else scorer.check
        self._leaks = () if check is None else _label_leaks(self._git, commit, check, workloads)  # fmt: skip
        if check is not None and self._leaks:
            where = _printable(", ".join(self._leaks))
            self._note("baseline", [
                f"quality check {check.name!r}: the labels also appear in {where};"
                " a workload can read them there, so the check is sound only if"
                " none does"
            ])  # fmt: skip
        before = repo_fingerprint(self._git)
        failed: RunFailure | None = None
        rows: tuple[Measurement, ...] = ()
        with owned_phases(self._git, self._what, dirs):
            handle = self._git.add_worktree(dirs.worktree, commit)
            phase = self._make_phase(handle, dirs)
            try:
                _, rows = self._measure(
                    phase,
                    workloads,
                    prefix="baseline",
                    trial_id=None,
                    baseline_count=None,
                    baseline=True,
                )
            except RunFailure as failure:
                failed = failure
            if self._scorer_notes is not None:
                scorer_notes = self._scorer_notes.drain()
                self._note("baseline", [f"the quality scorer: {n}" for n in scorer_notes])  # fmt: skip
            self._tampered(before)
        if failed is not None:
            raise EngineError(f"the baseline could not be measured: {failed.reason}")
        return rows

    def calibrate(
        self, workloads: Sequence[Workload], *, run_id: str, commit: str, blocks: int
    ) -> NoiseCalibration:
        """The ``NoiseCalibrator`` (D41 c): ``blocks`` A/A blocks, each every
        workload ABBA at ``commit`` against a second worktree at ``commit``
        (no suite). A gap is the relative difference of the wall-time means,
        ``|A - A'| / max(A, A')`` (the gain a judge would read from pure noise),
        keyed ``<workload id>:wall_time_s``, the largest over the blocks; the floor
        is ``max(NOISE_FLOOR_MIN, NOISE_GAP_MULTIPLIER x the largest gap)``.
        Only wall time is calibrated: a user's own ``cpu_time_s`` objective
        relies on the 2 % minimum floor and its own noise judge. A
        ``RunFailure`` is an ``EngineError`` once F1 held."""
        if not 1 <= blocks <= NOISE_CALIBRATION_BLOCKS_MAX:
            raise ValueError(
                f"blocks must be 1-{NOISE_CALIBRATION_BLOCKS_MAX}, got {blocks}"
            )
        require_dir_name("run id", run_id)
        sides = [phase_dirs(run_id, name) for name in CALIBRATE_PHASES]
        before = repo_fingerprint(self._git)
        failed: RunFailure | None = None
        gaps: dict[str, float] = {}
        with owned_phases(self._git, CALIBRATION, *sides):
            a, b = (
                self._make_phase(self._git.add_worktree(d.worktree, commit), d)
                for d in sides
            )
            try:
                for _ in range(blocks):
                    for workload in workloads:
                        paired = measure_abab(a, b, workload)
                        self._note("calibration", paired.notes)
                        for key, gap in _gaps(paired.a, paired.b):
                            gaps[key] = max(gap, gaps.get(key, 0.0))
            except RunFailure as failure:
                self._note("calibration", failure.notes)
                failed = failure
            self._tampered(before, what=CALIBRATION)
        if failed is not None:
            raise EngineError(
                f"the noise calibration could not be measured: {failed.reason}"
            )
        largest = max(gaps.values(), default=0.0)
        floor = max(NOISE_FLOOR_MIN, settings.NOISE_GAP_MULTIPLIER * largest)
        return NoiseCalibration(blocks=blocks, gaps=gaps, floor=floor)


def _gaps(
    a: Sequence[Measurement], b: Sequence[Measurement]
) -> list[tuple[str, float]]:
    """Each time metric's relative gap between the A and A' rows (0 for two
    zero means)."""
    means = {(m.workload_id, m.metric): m.stats.mean for m in b}
    found: list[tuple[str, float]] = []
    for row in a:
        if row.metric in _TIME_METRICS:
            other = means[(row.workload_id, row.metric)]
            top = max(row.stats.mean, other)
            gap = abs(row.stats.mean - other) / top if top > 0 else 0.0
            found.append((f"{row.workload_id}:{row.metric}", gap))
    return found


class GitTrialRunner(_PhaseOwner):
    """The real ``TrialRunner`` for one project (module docstring for the steps).

    ``editor`` builds the run's ``CodeEditor`` from the run's module roots and
    reserved modules (``run_scope``), so the editor refuses what
    ``check_capture`` would reject; one is built per distinct scope. Its brief
    gains ``INVOKE_PROTECTED`` when invoke runs. ``cost_usd`` is the larger of
    the editor's report and its ``Budget``'s record; above ``budget_usd`` the
    trial fails charged exactly ``budget_usd`` (and the same share of tokens).
    ``fix_retries`` (0-1, default 0: off) and ``retry_floor_usd`` bound the fix
    retry (module docstring). ``paired`` (default off: Step 2; the factory
    passes ``PAIRED_TRIALS``) measures every attempt against a twin of the
    base (module docstring). Notes (``RunSample``, ``RunFailure``,
    ``Measured``) go to ``on_note``
    prefixed ``trial for hypothesis <id>:``. ``prefix`` is the engine branch
    prefix (default the setting's; the factory passes the context's): the
    branch must be ``<prefix>trial-<run>-<hyp>`` and only refs under it move.
    """

    _what = "the trial"

    def __init__(
        self,
        project: Project,
        *,
        editor: EditorFactory,
        git: GitWorkspace | None = None,
        network: IsolationMode | None = None,
        fs: IsolationMode | None = None,
        platform: str = sys.platform,
        base_env: Mapping[str, str] | None = None,
        run: RunOnce = run_once,
        on_note: Callable[[str], None] | None = None,
        prefix: str | None = None,
        fix_retries: int = 0,
        retry_floor_usd: float = 0.0,
        paired: bool = False,
        scorer: RunnerScorer | None = None,
    ) -> None:
        if not 0 <= fix_retries <= FIX_RETRIES_MAX:
            raise ValueError(
                f"fix_retries must be 0-{FIX_RETRIES_MAX}, got {fix_retries}"
            )
        if not math.isfinite(retry_floor_usd) or retry_floor_usd < 0:
            raise ValueError(
                f"retry_floor_usd must be finite and at least 0, got {retry_floor_usd}"
            )
        self._fix_retries, self._retry_floor = fix_retries, retry_floor_usd
        self._paired = paired
        super().__init__(
            project, git=git, network=network, fs=fs, platform=platform,
            base_env=base_env, run=run, on_note=on_note, scorer=scorer,
        )  # fmt: skip
        self._prefix = settings.TRIAL_BRANCH_PREFIX if prefix is None else prefix
        problem = branch_prefix_problem(self._prefix)
        if problem is not None:
            raise ValueError(f"branch prefix {self._prefix[:300]!r} {problem}")
        self._editor_factory = editor
        self._editors: dict[tuple[frozenset[str], frozenset[str]], CodeEditor] = {}

    def run(
        self,
        hypothesis: Hypothesis,
        workloads: Sequence[Workload],
        baseline: Baseline,
        *,
        round: int,
        branch: str,
        budget_usd: float,
        brief: TrialBrief,
    ) -> Trial:
        if not math.isfinite(budget_usd) or budget_usd < 0:
            raise ValueError(
                f"budget_usd must be finite and at least 0, got {budget_usd}"
            )
        if baseline.commit is None:
            raise ValueError("the trial needs the baseline's commit, got None")
        run_id = _run_id(branch, hypothesis.id, self._prefix)
        recorded = baseline.quality_files  # a resumed run's scorer freezes here
        self._quality.freeze(self._git, run_id, baseline.commit, recorded=recorded)
        dirs = phase_dirs(run_id, f"trial-{hypothesis.id}")
        own_ref = f"refs/heads/{branch}"
        exclude = frozenset({own_ref})
        draft = Trial(
            id=trial_id_for(branch, round),
            hypothesis_id=hypothesis.id,
            round=round,
            worktree_path=str(dirs.worktree),
            branch=branch,
            base_commit=baseline.commit,
            status=TrialStatus.failed,
            started_at=utc_now(),
        )
        before = repo_fingerprint(self._git, exclude_refs=exclude)
        prior = self._git.ref_value(own_ref)
        self._refuse_checked_out(own_ref)
        if prior is not None and not self._ours(prior, draft.id):
            raise EngineError(
                f"{own_ref} exists at {prior}, which is not this trial's commit"
                f" (no '{TRAILER}: {draft.id}' trailer); delete it to run the trial"
            )
        progress = _Progress(Budget(budget_usd))
        twin = (_twin_dirs(dirs),) if self._paired else ()
        try:
            with owned_phases(self._git, self._what, dirs, *twin):
                handle = self._git.add_worktree(dirs.worktree, baseline.commit)
                trial = self._attempt(
                    handle, dirs, draft, hypothesis, workloads, baseline, brief,
                    prior, progress,
                )  # fmt: skip
                if trial.commit is None and prior is not None:
                    self._refuse_checked_out(own_ref)
                    self._git.delete_ref(own_ref, prior, prefix=self._prefix)
                self._tampered(before, exclude)
                if self._git.ref_value(own_ref) != trial.commit:
                    raise RepoTamperedError(
                        f"the trial's own ref {own_ref} moved while the trial ran"
                    )
        except Exception as exc:  # the trial is lost: keep its cost, drop its ref
            self._undo_own_ref(own_ref, prior, progress.moved, hypothesis.id)
            add_spend(exc, *progress.spent(budget_usd))
            raise
        return trial.model_copy(update={"finished_at": utc_now()})

    def _undo_own_ref(
        self, ref: str, prior: str | None, moved: str | None, hypothesis_id: str
    ) -> None:
        """Put the own ref back where it was before this trial moved it; a ref
        someone else moved since stays where they put it, and so does one a
        worktree checked out meanwhile (moving it would move that HEAD; a note
        says so)."""
        if moved is None:
            return
        with contextlib.suppress(GitError):
            if self._checked_out(ref):
                self._note(
                    f"trial for hypothesis {hypothesis_id}",
                    [
                        f"{ref} was left alone (the aborted trial had moved it"
                        f" to {moved}): a worktree has it checked out"
                    ],
                )
            elif prior is None:
                self._git.delete_ref(ref, moved, prefix=self._prefix)
            else:
                self._git.update_ref(ref, prior, moved, prefix=self._prefix)

    def _ours(self, commit: str, trial_id: str) -> bool:
        """Whether ``commit``'s last message paragraph has this trial's trailer."""
        message = self._git.commit_message(commit).rstrip(b"\n")
        last = message.rsplit(b"\n\n", 1)[-1].split(b"\n")
        return f"{TRAILER}: {trial_id}".encode() in last

    def _editor(self, scope: RunScope) -> CodeEditor:
        key = (scope.module_roots, scope.reserved_modules)
        if key not in self._editors:
            self._editors[key] = self._editor_factory(
                module_roots=scope.module_roots, reserved_modules=scope.reserved_modules
            )
        return self._editors[key]

    def _attempt(
        self,
        handle: WorktreeHandle,
        dirs: PhaseDirs,
        trial: Trial,
        hypothesis: Hypothesis,
        workloads: Sequence[Workload],
        baseline: Baseline,
        brief: TrialBrief,
        prior: str | None,
        progress: _Progress,
    ) -> Trial:
        """Steps 2 to 6, then at most one fix retry; every outcome but an
        exception is a Trial (draft: failed). ``progress`` records the spend and
        the own ref's move as they happen."""
        base = str(baseline.commit)
        tracked = self._git.ls_tree(base)
        scope = run_scope(self._project, workloads, tracked, worktree=handle.path)
        frozen = self._quality.mask  # literal: shown as is, escaped to match
        protected = tuple(dict.fromkeys((*brief.protected, *scope.protected, *frozen)))
        read_deny = tuple(dict.fromkeys((*brief.read_deny, *frozen)))
        patterns = tuple(glob.escape(p) if p in frozen else p for p in protected)
        job = _Job(
            handle, dirs, hypothesis, tuple(workloads), baseline, base, tracked,
            scope, replace(brief, protected=protected, read_deny=read_deny), prior,
            f"refs/heads/{trial.branch}", _twin_dirs(dirs), patterns,
        )  # fmt: skip
        task = EditTask(hypothesis, job.brief, secrets.token_hex(8))
        first = self._try(job, trial, task, progress, earlier=None)
        if first.crash is None:
            return self._reparse(job, trial, first, progress)
        return self._retry(job, trial, first, first.crash, progress)

    def _try(
        self,
        job: _Job,
        trial: Trial,
        task: EditTask,
        progress: _Progress,
        *,
        earlier: EditResult | None,
    ) -> _Tried:
        """One attempt: edit, capture, check, commit, measure. ``earlier`` is
        the first attempt's record on a retry: the writes merge (D15), the
        commit's parent is the base and an unaffordable edit is a failure."""
        budget = progress.budget
        edited = self._editor(job.scope).edit(job.handle.path, task, budget)
        result = edited if earlier is None else _merged(earlier, edited)
        trial = progress.trial = _charged(trial, result, budget, budget.cap_usd)
        self._git.check_link(job.handle)
        untouched = not result.written and trial.cost_usd == 0 and not trial.tokens_used
        if earlier is None and result.stop == STOP_BUDGET and untouched:
            raise TrialUnaffordable(
                result.error or "the run's cost cap stopped the edit"
            )
        if trial.error is not None:
            return _Tried(trial, result)
        if result.error is not None or result.stop != _EDIT_DONE:
            reason = result.error or "no reason given"
            stopped = f"the editor stopped ({result.stop}): {reason}"
            return _Tried(_failed(trial, stopped), result)
        over = None if earlier is None else _over_limits(result.written)
        if over is not None:
            return _Tried(_failed(trial, over), result)
        try:
            self._git.stage_all(job.handle)
            changes = self._git.changes(job.handle, job.base)
            bad = [ascii(c.path) for c in changes if not is_utf8(c.path)]
            if bad:
                text = f"the diff names {bad[0]}, a path that is not valid UTF-8"
                return _Tried(_failed(trial, text), result)
            if not changes:
                return _Tried(_failed(trial, "the editor changed nothing"), result)
            diff = self._git.diff(job.handle, job.base)
            blobs = {  # what check_capture reads: added or modified regular files
                c.path: self._git.staged_blob(job.handle, c.path)
                for c in changes
                if c.status in ("A", "M") and c.new_mode in _REGULAR
            }
            frozen = self._quality.mask  # D37's tripwire, base and patch lazily
            modified = {c.path for c in changes if c.status == "M" and c.new_mode in _REGULAR}  # fmt: skip
            base_of = functools.partial(_base_of, self._git, job.base, modified)
            patch = functools.partial(_stream_added, self._git, job.handle, job.base)
            references = check_quality_references(blobs, base_of, frozen, patch)
            violations = self._violations(  # base_of: the spawn delta's base (D62)
                changes, result, blobs, job.baseline, job.scope, job.tracked,
                job.patterns, base_of,
            ) + references  # fmt: skip
        except GitError as error:  # RepoTamperedError is no GitError: it propagates
            text = f"the change could not be captured: {error}"
            return _Tried(_failed(trial, text), result)
        touched = tuple(c.path for c in changes)
        trial = trial.model_copy(update={"diff": diff, "touched_paths": touched})
        if violations:
            text = "; ".join(v.message for v in violations[:3])
            reason = f"the change breaks {len(violations)} anti-cheat rule(s): {text}"
            return _Tried(_failed(trial, reason, violations=violations), result)
        message = _message(job.hypothesis, trial.id)
        parent = None if earlier is None else job.base
        commit = self._git.commit(job.handle, message, base=job.base, parent=parent)
        self._git.clean(job.handle)
        self._point(job, commit, progress)
        trial = trial.model_copy(update={"commit": commit})
        side = _Side()
        phase, twin = self._trial_phases(job, side)
        try:
            base, rows = self._measure(
                phase,
                job.workloads,
                prefix=f"trial for hypothesis {job.hypothesis.id}",
                trial_id=trial.id,
                baseline_count=baseline_test_count(job.baseline.measurements),
                twin=twin,
            )
        except RunFailure as failure:
            if (
                side.twin
            ):  # the base failed: no retry, no verdict (run() adds the spend)
                raise EngineError(f"{TWIN_FAILED}: {failure.reason}") from None
            return _Tried(_failed(trial, failure.reason), result, failure)
        measured = {
            "status": TrialStatus.measured,
            "measurements": rows,
            "base_measurements": base,
        }
        return _Tried(trial.model_copy(update=measured), result)

    def _trial_phases(self, job: _Job, side: _Side) -> tuple[Phase, Phase | None]:
        """The trial's phase and, when paired, a fresh twin's at the base (an
        existing twin, a first attempt's, is replaced); both mark ``side``."""
        phase = self._make_phase(job.handle, job.dirs)
        if not self._paired:
            return phase, None
        handle = self._git.add_worktree(job.twin.worktree, job.base)
        twin = self._make_phase(handle, job.twin)
        return _marked(phase, side, False), _marked(twin, side, True)

    def _point(self, job: _Job, commit: str, progress: _Progress) -> None:
        """Move the own ref from where this trial left it to ``commit``."""
        current = progress.moved or job.prior
        if commit != current:
            self._refuse_checked_out(job.own_ref)  # checked out meanwhile
            self._git.update_ref(job.own_ref, commit, current, prefix=self._prefix)
            progress.moved = commit

    def _retry(
        self,
        job: _Job,
        draft: Trial,
        first: _Tried,
        crash: RunFailure,
        progress: _Progress,
    ) -> Trial:
        """At most one fix retry of an own fixable crash (D12-D15): a fresh
        request carrying only the closed feedback's ``render()``, on the reset
        worktree, with a new token and the same budget. Any way it does not run
        or does not hold keeps the first failure, noted; the notes, never the
        prompt, carry what was withheld."""
        fixable = self._feedback(job, first.trial, crash, _NO_CLOSURE)
        if fixable is None or first.trial.attempts > self._fix_retries:
            return first.trial
        kind = fixable.exc_type
        refused = self._not_allowed(job, first.trial, kind, progress.budget)
        if refused is not None:
            return refused
        closure = self._closure(job, first.trial)
        feedback = self._feedback(job, first.trial, crash, closure) or fixable
        why = feedback.withheld
        withheld = "" if why is None else f"; message withheld: {why}"
        task = EditTask(
            job.hypothesis, job.brief, secrets.token_hex(8), feedback=feedback.render()
        )
        self._git.reset(job.handle)  # attempt 1's commit, without the run's files
        retried = draft.model_copy(update={"attempts": first.trial.attempts + 1})
        second = self._try(job, retried, task, progress, earlier=first.result)
        if second.trial.status is TrialStatus.measured:
            return _noted(second.trial, f"{kind}; retried{withheld}")
        self._point(job, str(first.trial.commit), progress)
        return _kept(first.trial, second, f"{kind}{withheld}")

    def _reparse(
        self, job: _Job, draft: Trial, first: _Tried, progress: _Progress
    ) -> Trial:
        """At most one re-edit of a first edit refused only as unparsable
        (N0b, module docstring), under the fix retry's caps; anything else
        returns ``first``'s trial as it is."""
        feedback = _parse_feedback(first.trial, job.brief.read_deny)
        if feedback is None or first.trial.attempts > self._fix_retries:
            return first.trial
        refused = self._not_allowed(job, first.trial, _UNPARSABLE, progress.budget)
        if refused is not None:
            return refused
        task = EditTask(
            job.hypothesis, job.brief, secrets.token_hex(8), feedback=feedback
        )
        retried = draft.model_copy(update={"attempts": first.trial.attempts + 1})
        second = self._try(job, retried, task, progress, earlier=first.result)
        if second.trial.status is TrialStatus.measured:
            return _noted(second.trial, f"{_UNPARSABLE}; retried")
        self._unpoint(job, progress)
        return _kept(first.trial, second, _UNPARSABLE)

    def _not_allowed(
        self, job: _Job, trial: Trial, kind: str, budget: Budget
    ) -> Trial | None:
        """``trial`` noted when the run's fix retry is spent or the budget is
        below the retry floor; ``None`` when a retry may run."""
        if trial.attempts - 1 >= job.brief.fix_retries_left:
            return _noted(trial, f"{kind}; not retried: the run's fix retry is spent")
        if budget.remaining < self._retry_floor:
            return _noted(
                trial,
                f"{kind}; not retried: {budget.remaining:.6f} USD left, below"
                f" the retry floor of {self._retry_floor:.6f} USD",
            )
        return None

    def _unpoint(self, job: _Job, progress: _Progress) -> None:
        """Put the own ref back where the trial found it (a kept refusal has no
        commit); ``run`` then drops a prior ref as for any trial without one."""
        moved = progress.moved
        if moved is None:
            return
        self._refuse_checked_out(job.own_ref)
        if job.prior is None:
            self._git.delete_ref(job.own_ref, moved, prefix=self._prefix)
        else:
            self._git.update_ref(job.own_ref, job.prior, moved, prefix=self._prefix)
        progress.moved = None

    def _feedback(
        self, job: _Job, trial: Trial, crash: RunFailure, closure: ClosureIndex
    ) -> TrialFeedback | None:
        workdir = next(
            (w.working_dir for w in job.workloads if w.id == crash.workload_id), "."
        )
        return classify(
            crash, closure=closure, worktree=job.handle.path, tracked=job.tracked,
            touched=trial.touched_paths, working_dir=workdir,
        )  # fmt: skip

    def _closure(self, job: _Job, trial: Trial) -> ClosureIndex:
        """D13's closure, read from git and never from the worktree a run may
        have rewritten: the tracked ``.py`` blobs at the base, neither
        deny-listed nor in the brief's ``read_deny`` (the frozen files),
        and the touched files at the trial's commit, at most the setting's
        bytes (past it the index is incomplete and messages are withheld)."""
        cap, used = settings.RETRY_CLOSURE_MAX_SOURCE_BYTES, 0
        sources: dict[str, str] = {}
        for path in job.tracked:
            if used > cap:
                break
            denied = _read_denied(path) or path in job.brief.read_deny
            if path.endswith(".py") and not denied:
                blob = self._git.read_blob(job.base, path, limit=cap - used + 1)
                used += len(blob)
                sources[path] = blob.decode("utf-8", "replace")
        commit = str(trial.commit)
        present = frozenset(self._git.ls_tree(commit))
        at_commit = {
            path: self._git.read_blob(commit, path, limit=cap + 1).decode(
                "utf-8", "replace"
            )
            if path in present
            else None
            for path in trial.touched_paths
        }
        return ClosureIndex.build(
            trial.diff, sources, at_commit=at_commit, max_source_bytes=cap
        )

    @staticmethod
    def _violations(
        changes: Sequence[Change],
        result: EditResult,
        blobs: Mapping[str, bytes],
        baseline: Baseline,
        scope: RunScope,
        tracked: Collection[str],
        protected: Sequence[str],
        base_of: Callable[[str], bytes | None],
    ) -> tuple[Violation, ...]:
        judged = {o.metric for o in baseline.objectives}
        judged |= {g.metric for g in baseline.guardrails if g.metric is not None}
        captured = check_capture(
            changes,
            result.written,
            blobs,
            frozenset(judged),
            reserved_modules=scope.reserved_modules,
            module_roots=scope.module_roots,
            existing_dirs=_base_dirs(tracked),
            base_of=base_of,
        )
        return (*captured, *check_diff_all((c.path for c in changes), protected))


def _base_of(
    git: GitWorkspace, base: str, modified: AbstractSet[str], path: str
) -> bytes | None:
    """``path``'s content at ``base`` when the trial modified it, else ``None``
    (an added file); ``GitError`` past ``MAX_OUTPUT_BYTES`` fails closed."""
    return git.read_blob(base, path) if path in modified else None


def _stream_added(
    git: GitWorkspace, handle: WorktreeHandle, base: str, path: str,
    sink: Callable[[bytes], None],
) -> None:  # fmt: skip
    """``path``'s staged ``-U0`` patch against ``base`` into ``sink``, nothing
    kept: ``diff``'s flags (no renames, external diff or textconv), a literal
    pathspec. ``GitWorkspace`` has no public streaming patch, so its own
    ``_git`` and flags are used (git.py is not this unit's)."""
    argv = (*_DIFF, *_PATCH, "-U0", "--cached", _require_oid(base), "--")
    git._git(handle, *argv, f":(literal){_require_path(path)}", limit=0, sink=sink)


def _run_id(branch: str, hypothesis_id: str, prefix: str) -> str:
    """The run id inside ``<prefix>trial-<run>-<hypothesis id>``."""
    require_dir_name("hypothesis id", hypothesis_id)
    head, tail = f"{prefix}trial-", f"-{hypothesis_id}"
    inner = branch[len(head) : len(branch) - len(tail)]
    if not (branch.startswith(head) and branch.endswith(tail) and inner):
        raise ValueError(f"branch {branch!r} is not {head}<run>{tail}")
    require_dir_name("run id", inner)
    return inner


def _printable(text: str) -> str:
    return "".join(ch if ch.isprintable() else "?" for ch in text)


def _noted(trial: Trial, note: str) -> Trial:
    return trial.model_copy(update={"retry_notes": (*trial.retry_notes, note)})


def _kept(first: Trial, second: _Tried, kind: str) -> Trial:
    """``first`` kept after a retry that did not hold, with both attempts'
    spend and a note naming what the retry did (engine text, or the type of
    its crash: the raw reason stays in ``error`` only)."""
    what = second.trial.error  # engine text: a stop, a rule, a limit
    if second.crash is not None:
        again = parse_traceback(second.crash.exit_tail)
        what = "crashed again" if again is None else again.exc_type[:_TYPE_CHARS]
    kept = first.model_copy(
        update={
            "attempts": second.trial.attempts,
            "cost_usd": second.trial.cost_usd,
            "tokens_used": second.trial.tokens_used,
        }
    )
    return _noted(kept, f"{kind}; retry: {what}, {_KEPT}")


def _parse_feedback(trial: Trial, read_deny: Collection[str]) -> str | None:
    """N0b's feedback: the engine message of each of ``trial``'s violations,
    one a line, ASCII-escaped, when every one is ``unparsable_source`` on a
    path the editor may read (neither deny-listed nor in ``read_deny``);
    else ``None``. The message names the file, the line and the parser's
    message, escaped and capped by ``anticheat._parse``."""
    found = trial.violations
    if not found or any(
        v.rule is not ViolationRule.unparsable_source
        or v.path is None
        or _read_denied(v.path)
        or v.path in read_deny
        for v in found
    ):
        return None
    return "\n".join(
        v.message.encode("ascii", "backslashreplace").decode() for v in found
    )


def _read_denied(path: str) -> bool:
    return any(matches_pattern(path, pattern) for pattern in READ_DENY_PATTERNS)


def _merged(first: EditResult, second: EditResult) -> EditResult:
    """Both attempts' record (D15): bytes per path add up, so every path of the
    union diff is recorded; so does the spend; the stop is the second's."""
    written = dict(first.written)
    for path, size in second.written.items():
        written[path] = written.get(path, 0) + size
    usd, tokens = (
        first.cost_usd + second.cost_usd,
        first.tokens_used + second.tokens_used,
    )
    return EditResult(written, usd, tokens, second.stop, second.error)


def _over_limits(written: Mapping[str, int]) -> str | None:
    """Why the attempts together wrote more than one trial may, or ``None``."""
    limits = EditorLimits.from_settings()
    files, total = len(written), sum(written.values())
    largest = max(written.values(), default=0)
    if (
        files <= limits.max_files
        and total <= limits.max_total_bytes
        and largest <= limits.max_file_bytes
    ):
        return None
    return (
        f"the attempts together wrote {files} files and {total} bytes ({largest}"
        f" in one file), over the trial's write limits ({limits.max_files} files,"
        f" {limits.max_total_bytes} bytes, {limits.max_file_bytes} bytes per file)"
    )


def _failed(
    trial: Trial, error: str, *, violations: tuple[Violation, ...] = ()
) -> Trial:
    return trial.model_copy(update={"error": error, "violations": violations})


def _charged(trial: Trial, result: EditResult, budget: Budget, cap: float) -> Trial:
    """The money spent; above ``cap``, failed and charged ``cap`` exactly."""
    spent = max(result.cost_usd, budget.spent_usd)
    tokens = max(result.tokens_used, budget.tokens)
    if spent <= cap:
        return trial.model_copy(update={"cost_usd": spent, "tokens_used": tokens})
    error = f"the editor reported {spent:.6f} USD, above the trial's budget of {cap:.6f} USD"
    capped = math.floor(tokens * cap / spent)
    return trial.model_copy(
        update={"cost_usd": cap, "tokens_used": capped, "error": error}
    )


def _message(hypothesis: Hypothesis, trial_id: str) -> str:
    title = "".join(ch if ch.isprintable() else " " for ch in hypothesis.title)
    subject = title[:_SUBJECT_CHARS].strip() or hypothesis.id
    return (
        f"engine trial: {subject}\n\nHypothesis: {hypothesis.id}\n"
        f"{TRAILER}: {trial_id}\n"
    )
