"""The real runners: one trial (``GitTrialRunner``) and the baseline (``GitBaselineRunner``).

Both own their phase (decision 38): ``<WORKTREE_ROOT>/<run>/<phase>`` at the
pinned commit plus ``<run>/_scratch/<phase>`` and ``<run>/_probe/<phase>``
(``measure.make_phase``: sandbox, environment, the reset before every run),
fingerprinted before and after (``repo_fingerprint``, decision 16), and in
``finally`` removed again: ``worktree remove --force``, a contained ``rmtree``,
``prune``, then ``rmdir <run>`` when empty. Cleanup never follows a link a
workload planted in place of an engine dir or its parent; a dir it cannot
remove safely is an ``EngineError`` after every step ran, unless an error is
already on its way (the profiler's hardened cleanup, copied until U20 factors
it out).

A trial (spec section 4, steps 1 to 8) is ``trial-<hypothesis id>``: the
editor edits the worktree; the change is captured (``--no-renames``, strict
UTF-8, a ``GitError`` fails the trial); ``check_capture`` and
``check_diff_all`` run; any violation fails it and it is **never executed**.
Otherwise it is committed with the engine identity, the base dates and an
``Engine-Trial: <id>`` trailer, ``clean -ffdx``-ed and put on its own ref
``refs/heads/engine/trial-<run>-<hyp>`` (decision 18: the id is
``uuid5(branch@round)``; an existing ref moves only when its commit carries
this trial's trailer, else ``EngineError``; a re-run that commits nothing
drops it), then measured with the baseline's test count. F1 excludes only the
own ref, which must then be absent or at ``Trial.commit``
(``RepoTamperedError``). The editor, cost and the run notes: see
``GitTrialRunner``.
"""

from __future__ import annotations

import contextlib
import functools
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
from autonomous_ai_agents.common.config import IsolationMode, settings
from autonomous_ai_agents.common.errors import EngineError, RepoTamperedError
from autonomous_ai_agents.common.models import (
    Baseline,
    Hypothesis,
    Measurement,
    Project,
    Trial,
    TrialStatus,
    Violation,
    Workload,
    utc_now,
)
from autonomous_ai_agents.common.paths import RESERVED_MODULES, normalize_path
from autonomous_ai_agents.common.refnames import refname_problem
from autonomous_ai_agents.execution.git import (
    GitError,
    GitWorkspace,
    _contained,
    _rmtree,
    repo_fingerprint,
)
from autonomous_ai_agents.execution.measure import (
    Phase,
    RunOnce,
    _python_module,
    baseline_test_count,
    make_phase,
    measure_workload,
    run_tests,
)
from autonomous_ai_agents.execution.procrun import RunFailure, run_once
from autonomous_ai_agents.execution.protocols import (
    Change,
    CodeEditor,
    EditResult,
    EditTask,
    TrialBrief,
    WorktreeHandle,
)
from autonomous_ai_agents.optimization.anticheat import (
    DEFAULT_MODULE_ROOTS,
    _is_utf8,
    check_capture,
    check_diff_all,
)

TRIAL_NAMESPACE = uuid.UUID("3f0c6a52-7d1e-5b9a-8c4f-2e6d9b1a7c30")
"""uuid5 namespace of trial ids: ``uuid5(TRIAL_NAMESPACE, "<branch>@<round>")``."""
TRAILER = "Engine-Trial"
BASELINE_PHASE = "baseline"
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
        found = _python_module(argv)
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


def _require_name(what: str, value: str) -> None:
    problem = "it contains '/'" if "/" in value else refname_problem(value)
    if problem is not None:
        raise ValueError(f"{what} {value!r} is not a safe directory name: {problem}")


def _remove(path: Path) -> None:
    """Remove an engine dir the workload could write; a link planted in its
    place or in its parent's is unlinked, never followed; ``ValueError`` when
    ``<run>`` no longer resolves inside ``WORKTREE_ROOT``."""
    parent = _contained(path.parent)
    if os.path.islink(parent):
        os.unlink(parent)
        return
    target = _contained(path)
    if os.path.isdir(target) and not os.path.islink(target):
        _rmtree(target)
    elif os.path.lexists(target):
        os.unlink(target)


def _step(left: list[str], what: str, action: Callable[..., None], *args: Path) -> None:
    """One cleanup step; a ``GitError`` (a timeout), an ``OSError`` (a file a
    workload made unremovable) or a ``ValueError`` (``<run>`` is a link out of
    ``WORKTREE_ROOT``) is appended to ``left`` instead of raised."""
    try:
        action(*args)
    except ValueError:
        left.append(
            f"{what!r}: it no longer resolves inside WORKTREE_ROOT (a link was"
            " planted in place of the run directory)"
        )
    except (GitError, OSError) as error:
        left.append(f"{what!r}: {error}")


@dataclass(frozen=True)
class _Dirs:
    run: Path
    worktree: Path
    scratch: Path
    probe: Path


class _PhaseOwner:
    """What both runners share: git, the phase factory, notes, the cleanup."""

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
    ) -> None:
        self._project = project
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

    def _make_phase(self, handle: WorktreeHandle, dirs: _Dirs) -> Phase:
        return self._phase(
            self._git, handle, scratch=dirs.scratch, probe=dirs.probe, run=self._run
        )

    def _measure(
        self,
        phase: Phase,
        workloads: Sequence[Workload],
        *,
        prefix: str,
        trial_id: str | None,
        baseline_count: int | None,
    ) -> tuple[Measurement, ...]:
        """``measure_workload`` per workload, then the suite once; notes emitted.
        ``RunFailure`` propagates, its notes emitted."""
        rows: list[Measurement] = []
        try:
            for workload in workloads:
                measured = measure_workload(phase, workload, trial_id=trial_id)
                self._note(prefix, measured.notes)
                rows.extend(measured.measurements)
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
        return (*rows, *suite.measurements)

    @staticmethod
    def _dirs(run_id: str, phase: str) -> _Dirs:
        run = settings.WORKTREE_ROOT / run_id
        scratch, probe = run / "_scratch" / phase, run / "_probe" / phase
        return _Dirs(run, run / phase, scratch, probe)

    def _cleanup(self, dirs: _Dirs) -> list[str]:
        """Remove the worktree, then each dir, then prune; every step runs
        (the profiler's nesting). A step that fails (``_step``) is recorded,
        not raised, so an error already on its way wins; anything else still
        propagates once every later step ran. Returns what failed, and why."""
        left: list[str] = []
        try:
            _step(left, str(dirs.worktree), self._git.remove_worktree, dirs.worktree)
        finally:
            try:
                for path in (dirs.scratch, dirs.probe):
                    _step(left, str(path), _remove, path)
            finally:
                try:
                    _step(left, "the worktree registrations", self._git.prune)
                finally:
                    for path in (dirs.run / "_scratch", dirs.run / "_probe", dirs.run):
                        # not empty (another owner), or <run> is a planted link
                        with contextlib.suppress(OSError, ValueError):
                            os.rmdir(_contained(path))
        return left

    def _raise_left(self, left: Sequence[str]) -> None:
        if left:  # only when nothing else was raised: that error wins
            raise EngineError(
                f"{self._what} could not clean up {'; '.join(left)}; remove what"
                " is left by hand"
            )

    def _refuse_checked_out(self, ref: str) -> None:
        """Moving a branch a worktree has checked out moves that HEAD too."""
        if ref.casefold() in {b.casefold() for b in self._git.checked_out_branches()}:
            raise EngineError(
                f"refusing to move {ref}: it is checked out in a worktree; check"
                " out another branch there, then run the trial again"
            )

    def _tampered(self, before: str, exclude: frozenset[str] = frozenset()) -> None:
        if repo_fingerprint(self._git, exclude_refs=exclude) != before:
            raise RepoTamperedError(
                f"the repository changed while {self._what} ran: its refs, config"
                " or hooks differ from before the run"
            )


class GitBaselineRunner(_PhaseOwner):
    """The real ``BaselineRunner``: every workload at ``commit``, then the suite
    once (its ``tests_passed`` rows record the passing count trials must reach).
    A ``RunFailure`` is an ``EngineError`` once F1 held. Notes go to
    ``on_note`` prefixed ``baseline:``."""

    _what = "the baseline"

    def measure(
        self, workloads: Sequence[Workload], *, run_id: str, commit: str | None
    ) -> tuple[Measurement, ...]:
        if commit is None:
            raise ValueError("the baseline needs the pinned commit, got None")
        _require_name("run id", run_id)
        dirs = self._dirs(run_id, BASELINE_PHASE)
        before = repo_fingerprint(self._git)
        failed: RunFailure | None = None
        rows: tuple[Measurement, ...] = ()
        try:
            handle = self._git.add_worktree(dirs.worktree, commit)
            phase = self._make_phase(handle, dirs)
            try:
                rows = self._measure(
                    phase,
                    workloads,
                    prefix="baseline",
                    trial_id=None,
                    baseline_count=None,
                )
            except RunFailure as failure:
                failed = failure
            self._tampered(before)
        finally:
            left = self._cleanup(dirs)
        self._raise_left(left)
        if failed is not None:
            raise EngineError(f"the baseline could not be measured: {failed.reason}")
        return rows


class GitTrialRunner(_PhaseOwner):
    """The real ``TrialRunner`` for one project (module docstring for the steps).

    ``editor`` builds the run's ``CodeEditor`` from the run's module roots and
    reserved modules (``run_scope``), so the editor refuses what
    ``check_capture`` would reject; one is built per distinct scope. Its brief
    gains ``INVOKE_PROTECTED`` when invoke runs. ``cost_usd`` is the larger of
    the editor's report and its ``Budget``'s record; above ``budget_usd`` the
    trial fails charged exactly ``budget_usd`` (and the same share of tokens).
    Notes (``RunSample``, ``RunFailure``, ``Measured``) go to ``on_note``
    prefixed ``trial for hypothesis <id>:``.
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
    ) -> None:
        super().__init__(
            project, git=git, network=network, fs=fs, platform=platform,
            base_env=base_env, run=run, on_note=on_note,
        )  # fmt: skip
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
        dirs = self._dirs(_run_id(branch, hypothesis.id), f"trial-{hypothesis.id}")
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
        try:
            handle = self._git.add_worktree(dirs.worktree, baseline.commit)
            trial = self._attempt(
                handle, dirs, draft, hypothesis, workloads, baseline, brief,
                budget_usd, prior,
            )  # fmt: skip
            if trial.commit is None and prior is not None:
                self._refuse_checked_out(own_ref)
                self._git.delete_ref(own_ref, prior)
            self._tampered(before, exclude)
            if self._git.ref_value(own_ref) != trial.commit:
                raise RepoTamperedError(
                    f"the trial's own ref {own_ref} moved while the trial ran"
                )
        finally:
            left = self._cleanup(dirs)
        self._raise_left(left)
        return trial.model_copy(update={"finished_at": utc_now()})

    def _ours(self, commit: str, trial_id: str) -> bool:
        """Whether ``commit``'s last message paragraph has this trial's trailer."""
        raw = self._git._run("cat-file", "commit", commit)  # no public reader
        message = raw.partition(b"\n\n")[2].rstrip(b"\n")
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
        dirs: _Dirs,
        trial: Trial,
        hypothesis: Hypothesis,
        workloads: Sequence[Workload],
        baseline: Baseline,
        brief: TrialBrief,
        budget_usd: float,
        prior: str | None,
    ) -> Trial:
        """Steps 2 to 6; every outcome but an exception is a Trial (draft: failed)."""
        base = str(baseline.commit)
        tracked = self._git.ls_tree(base)
        scope = run_scope(self._project, workloads, tracked, worktree=handle.path)
        protected = tuple(dict.fromkeys((*brief.protected, *scope.protected)))
        task = EditTask(
            hypothesis, replace(brief, protected=protected), secrets.token_hex(8)
        )
        budget = Budget(budget_usd)
        result = self._editor(scope).edit(handle.path, task, budget)
        self._git.check_link(handle)
        trial = _charged(trial, result, budget, budget_usd)
        if trial.error is not None:
            return trial
        if result.error is not None or result.stop != _EDIT_DONE:
            reason = result.error or "no reason given"
            return _failed(trial, f"the editor stopped ({result.stop}): {reason}")
        try:
            self._git.stage_all(handle)
            changes = self._git.changes(handle, base)
            bad = [ascii(c.path) for c in changes if not _is_utf8(c.path)]
            if bad:
                return _failed(
                    trial, f"the diff names {bad[0]}, a path that is not valid UTF-8"
                )
            if not changes:
                return _failed(trial, "the editor changed nothing")
            diff = self._git.diff(handle, base)
            blobs = {  # what check_capture reads: added or modified regular files
                c.path: self._git.staged_blob(handle, c.path)
                for c in changes
                if c.status in ("A", "M") and c.new_mode in _REGULAR
            }
        except GitError as error:  # RepoTamperedError is no GitError: it propagates
            return _failed(trial, f"the change could not be captured: {error}")
        touched = tuple(c.path for c in changes)
        trial = trial.model_copy(update={"diff": diff, "touched_paths": touched})
        violations = self._violations(
            changes, result, blobs, baseline, scope, tracked, protected
        )
        if violations:
            text = "; ".join(v.message for v in violations[:3])
            reason = f"the change breaks {len(violations)} anti-cheat rule(s): {text}"
            return _failed(trial, reason, violations=violations)
        message = _message(hypothesis, trial.id)
        commit = self._git.commit(handle, message, base=base)
        self._git.clean(handle)
        if commit != prior:
            own_ref = f"refs/heads/{trial.branch}"
            self._refuse_checked_out(own_ref)  # checked out while the editor ran
            self._git.update_ref(own_ref, commit, prior)
        trial = trial.model_copy(update={"commit": commit})
        phase = self._make_phase(handle, dirs)
        try:
            rows = self._measure(
                phase,
                workloads,
                prefix=f"trial for hypothesis {hypothesis.id}",
                trial_id=trial.id,
                baseline_count=baseline_test_count(baseline.measurements),
            )
        except RunFailure as failure:
            return _failed(trial, failure.reason)
        return trial.model_copy(
            update={"status": TrialStatus.measured, "measurements": rows}
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
        )
        return (*captured, *check_diff_all((c.path for c in changes), protected))


def _run_id(branch: str, hypothesis_id: str) -> str:
    """The run id inside ``<prefix>trial-<run>-<hypothesis id>``."""
    _require_name("hypothesis id", hypothesis_id)
    head, tail = f"{settings.TRIAL_BRANCH_PREFIX}trial-", f"-{hypothesis_id}"
    inner = branch[len(head) : len(branch) - len(tail)]
    if not (branch.startswith(head) and branch.endswith(tail) and inner):
        raise ValueError(f"branch {branch!r} is not {head}<run>{tail}")
    _require_name("run id", inner)
    return inner


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
